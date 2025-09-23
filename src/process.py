# process.py
import socket
import threading
import json
import time
from message import Message, MessageType

HOST = "localhost"

class ResourceState:
    """Estados possíveis para um recurso"""
    RELEASED = "released"      # Não está usando e não quer usar
    WANTED = "wanted"         # Quer usar mas ainda não conseguiu
    HELD = "held"            # Está usando atualmente

class Process:
    """Processo com relógio lógico e capacidades de multicast totalmente ordenado."""
    
    def __init__(self, proc_id: str, port: int, other_ports: list, clock_increment: int = 1):
        self.proc_id = proc_id
        self.port = port
        self.other_ports = other_ports
        self.clock_increment = clock_increment
        
        # Lamport's logical clock
        self.logical_clock = 0
        self.clock_lock = threading.Lock()
        
        # Socket server
        self._server_socket = None
        self._running = threading.Event()
        
        # All processes in the group 
        self.all_ports = sorted([port] + other_ports) 
        port_to_process = {5000: "processo1", 5001: "processo2", 5002: "processo3"}
        self.all_processes = set([port_to_process[p] for p in self.all_ports])
        self.total_processes = len(self.all_processes)
        
        print(f"[{self.proc_id}] All processes in group: {sorted(list(self.all_processes))}")
        print(f"[{self.proc_id}] Total processes: {self.total_processes}")
        
        self.resource_states = {}
        self.resource_lock = threading.Lock()
        
        self.pending_requests = {}  
        self.request_lock = threading.Lock()
        
        
        self.request_queue = [] 
        self.queue_lock = threading.Lock()
        
        self.my_request_timestamps = {} 
        self.timestamp_lock = threading.Lock()
    
    def request_resource(self, resource_name: str):
        """
        Solicita acesso a um recurso
        """
        print(f"\n[{self.proc_id}] === SOLICITANDO RECURSO '{resource_name}' ===")
        
        current_state = self.get_resource_state(resource_name)
        if current_state == ResourceState.HELD:
            print(f"[{self.proc_id}] Erro: já possui o recurso '{resource_name}'")
            return
        
        if current_state == ResourceState.WANTED:
            print(f"[{self.proc_id}] Erro: já está aguardando o recurso '{resource_name}'")
            return
        
        # Incrementa o relógio e marca como WANTED
        timestamp = self.increment_clock()
        
        with self.resource_lock:
            self.resource_states[resource_name] = ResourceState.WANTED
            
        # Armazena o timestamp da nossa requisição para comparação
        with self.timestamp_lock:
            self.my_request_timestamps[resource_name] = timestamp
        
        # Cria mensagem de REQUEST
        request_msg = Message.create_request(
            sender=self.proc_id,
            logical_time=timestamp,
            resource_name=resource_name
        )
        
        # Inicializa contador de respostas (apenas grants serão contados)
        with self.request_lock:
            self.pending_requests[resource_name] = {
                "request_msg": request_msg,
                "replies_received": set()
            }
        
        print(f"[{self.proc_id}] Enviando REQUEST para todos os processos (ts: {timestamp})")
        
        self._multicast_message(request_msg)
        
        needed_replies = len(self.all_processes) - 1 
        print(f"[{self.proc_id}] Aguardando respostas (grants) de {needed_replies} processos...")

    def process_request(self, message: Message):
        """
        Processa uma mensagem REQUEST recebida seguindo as 3 regras do algoritmo Ricart-Agrawala:
        1. Se não estou interessado no recurso → enviar OK (granted=True)
        2. Se já tenho o recurso → enfileirar requisição e enviar REPLY deferred (granted=False)
        3. Se quero o recurso → comparar timestamps e decidir (responder OK ou DEFER)
        """
        resource_name = message.resource_name
        print(f"[{self.proc_id}] Processando REQUEST de {message.sender} para '{resource_name}' (ts: {message.logical_time})")
        
        current_state = self.get_resource_state(resource_name)
        
        if current_state == ResourceState.RELEASED:
            print(f"[{self.proc_id}] → CASO 1: Não tenho interesse no recurso '{resource_name}' - enviando GRANT (OK)")
            self.send_reply(message.sender, message.msg_id, granted=True)
            return
        
        if current_state == ResourceState.HELD:
            print(f"[{self.proc_id}] → CASO 2: Tenho o recurso '{resource_name}' - enfileirando requisição e enviando DEFER")
            self.queue_request(message)
            self.send_reply(message.sender, message.msg_id, granted=False)
            return
        
        if current_state == ResourceState.WANTED:
            with self.timestamp_lock:
                my_timestamp = self.my_request_timestamps.get(resource_name, float('inf'))
            
            print(f"[{self.proc_id}] → CASO 3: Ambos querem '{resource_name}' - comparando timestamps")
            print(f"[{self.proc_id}]   Meu timestamp: {my_timestamp}, Timestamp recebido: {message.logical_time}")
            
            if (message.logical_time < my_timestamp) or \
               (message.logical_time == my_timestamp and message.sender < self.proc_id):
                print(f"[{self.proc_id}]   → {message.sender} tem prioridade - enviando GRANT (OK)")
                self.send_reply(message.sender, message.msg_id, granted=True)
            else:
                print(f"[{self.proc_id}]   → Eu tenho prioridade - enfileirando requisição e enviando DEFER")
                self.queue_request(message)
                self.send_reply(message.sender, message.msg_id, granted=False)
            return

    def process_reply(self, message: Message):
        """
        Processa uma mensagem REPLY recebida.
        Conta apenas replies com granted == True (GRANT/OK).
        """
        print(f"[{self.proc_id}] Processando REPLY de {message.sender} (granted={message.granted})")
        
        # Encontra qual recurso está sendo respondido
        with self.request_lock:
            resource_found = None
            for resource_name, pending in self.pending_requests.items():
                if pending["request_msg"].msg_id == message.request_id:
                    resource_found = resource_name
                    break
            
            if resource_found is None:
                print(f"[{self.proc_id}] Warning: REPLY recebido para requisição desconhecida: {message.request_id}")
                return
            
            if not message.granted:
                print(f"[{self.proc_id}] Reply de {message.sender} é DEFERRED (não conta como permissão).")
                return
            
            self.pending_requests[resource_found]["replies_received"].add(message.sender)
            replies_count = len(self.pending_requests[resource_found]["replies_received"])
            needed_replies = len(self.all_processes) - 1  # Exceto nós mesmos
            
            print(f"[{self.proc_id}] GRANTs recebidos {replies_count}/{needed_replies} para '{resource_found}'")
            
            if replies_count >= needed_replies:
                print(f"[{self.proc_id}] ✓ Todas as permissões (GRANTs) recebidas para '{resource_found}'!")
                
                del self.pending_requests[resource_found]
                
                self.enter_critical_section(resource_found)

    def send_reply(self, to_process: str, request_id: str, granted: bool = True):
        """
        Envia uma mensagem REPLY para um processo, indicando se é GRANT (True) ou DEFER (False).
        """
        timestamp = self.increment_clock()
        
        reply_msg = Message.create_reply(
            sender=self.proc_id,
            logical_time=timestamp,
            request_id=request_id,
            granted=granted
        )
        
        # Encontra a porta do processo de destino
        process_to_port = {"processo1": 5000, "processo2": 5001, "processo3": 5002}
        target_port = process_to_port.get(to_process)
        
        if target_port is None:
            print(f"[{self.proc_id}] Erro: processo desconhecido '{to_process}'")
            return
        
        action = "GRANT" if granted else "DEFER"
        print(f"[{self.proc_id}] → Enviando REPLY ({action}) para {to_process} (req_id={request_id})")
        self._send_message_to_port(reply_msg, target_port)

    def enter_critical_section(self, resource_name: str):
        """
        Entra na seção crítica (obtém acesso exclusivo ao recurso).
        """
        print(f"\n[{self.proc_id}] ENTRANDO NA SEÇÃO CRÍTICA - Recurso '{resource_name}'")
        
        with self.resource_lock:
            self.resource_states[resource_name] = ResourceState.HELD
            
        with self.timestamp_lock:
            if resource_name in self.my_request_timestamps:
                del self.my_request_timestamps[resource_name]
        
        print(f"[{self.proc_id}] ✓ Acesso exclusivo ao recurso '{resource_name}' obtido!")
        print(f"[{self.proc_id}] Use 'release {resource_name}' para sair da seção crítica")

    def exit_critical_section(self, resource_name: str):
        """
        Sai da seção crítica (libera o recurso).
        """
        current_state = self.get_resource_state(resource_name)
        
        if current_state != ResourceState.HELD:
            print(f"[{self.proc_id}] Erro: não possui o recurso '{resource_name}' atualmente")
            return
        
        print(f"\n[{self.proc_id}] 🔓 SAINDO DA SEÇÃO CRÍTICA - Recurso '{resource_name}'")
        
        with self.resource_lock:
            self.resource_states[resource_name] = ResourceState.RELEASED
        
        self.process_queued_requests(resource_name)
        
        print(f"[{self.proc_id}] ✓ Recurso '{resource_name}' liberado!")

    def queue_request(self, message: Message):
        """
        Enfileira uma requisição para processar mais tarde.
        """
        with self.queue_lock:
            self.request_queue.append(message)
            print(f"[{self.proc_id}] Requisição de {message.sender} para '{message.resource_name}' enfileirada")

    def process_queued_requests(self, released_resource: str):
        """
        Processa requisições enfileiradas após liberar um recurso.
        """
        with self.queue_lock:
            if not self.request_queue:
                print(f"[{self.proc_id}] Nenhuma requisição enfileirada para processar")
                return
                
            requests_to_process = []
            remaining_queue = []
            
            for req in self.request_queue:
                if req.resource_name == released_resource:
                    requests_to_process.append(req)
                else:
                    remaining_queue.append(req)
            
            self.request_queue = remaining_queue
            
            if requests_to_process:
                print(f"[{self.proc_id}] Processando {len(requests_to_process)} requisições enfileiradas para '{released_resource}'")
                
                for req in requests_to_process:
                    print(f"[{self.proc_id}] → Enviando GRANT (OK) para {req.sender} (requisição enfileirada)")
                    self.send_reply(req.sender, req.msg_id, granted=True)
            else:
                print(f"[{self.proc_id}] Nenhuma requisição enfileirada para o recurso '{released_resource}'")

    def get_resource_state(self, resource_name):
        """
        Retorna o estado atual de um recurso.
        """
        resource_name = str(resource_name)
        
        with self.resource_lock:
            return self.resource_states.get(resource_name, ResourceState.RELEASED)

    def show_queue(self):
        """
        Mostra o conteúdo da fila de requisições.
        """
        with self.queue_lock:
            if not self.request_queue:
                print(f"[{self.proc_id}] Fila de requisições vazia")
            else:
                print(f"[{self.proc_id}] Fila de requisições ({len(self.request_queue)} itens):")
                for i, req in enumerate(self.request_queue):
                    print(f"  {i+1}. {req.sender} -> '{req.resource_name}' (ts: {req.logical_time})")
    
    def show_status(self):
        """
        Mostra o status detalhado do processo.
        """
        print(f"\n[{self.proc_id}] === STATUS DO PROCESSO ===")
        print(f"Clock atual: {self.get_clock()}")
        
        print("Estados dos recursos:")
        resources = [str(i) for i in range(1, 4)]  
        for resource in resources:
            state = self.get_resource_state(resource)
            print(f"  Recurso {resource}: {state}")
        
        with self.request_lock:
            if self.pending_requests:
                print("Requisições pendentes (aguardando GRANTs):")
                for resource, data in self.pending_requests.items():
                    replies_count = len(data["replies_received"])
                    needed = len(self.all_processes) - 1
                    print(f"  {resource}: {replies_count}/{needed} GRANTs recebidos")
            else:
                print("Nenhuma requisição pendente")
        
        with self.queue_lock:
            if self.request_queue:
                print(f"Fila de requisições recebidas ({len(self.request_queue)} itens):")
                for i, req in enumerate(self.request_queue):
                    print(f"  {i+1}. {req.sender} -> '{req.resource_name}' (ts: {req.logical_time})")
            else:
                print("Fila de requisições recebidas vazia")
        
        print("=" * 40)

    def _multicast_message(self, message: Message):
        """
        Envia mensagem para todos os outros processos.
        """
        for port in self.other_ports:
            self._send_message_to_port(message, port)

    def _send_message_to_port(self, message: Message, port: int):
        """
        Envia mensagem para um processo específico.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((HOST, port))
                s.send(json.dumps(message.to_dict()).encode())
                print(f"[{self.proc_id}] → Enviado {message.msg_type.value.upper()} para porta {port}")
        except Exception as e:
            print(f"[{self.proc_id}] Erro enviando mensagem para porta {port}: {e}")

    def start(self):
        """Iniciar o servidor do processo."""
        self._running.set()
        t = threading.Thread(target=self._serve, daemon=True)
        t.start()
    
    def _serve(self):
        """Loop principal do servidor para lidar com conexões de entrada."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, self.port))
        s.listen(5)
        self._server_socket = s
        print(f"[{self.proc_id}] escutando em {HOST}:{self.port}")
        
        try:
            while self._running.is_set():
                s.settimeout(1.0)
                try:
                    conn, addr = s.accept()
                    threading.Thread(target=self._handle_connection, args=(conn,), daemon=True).start()
                except socket.timeout:
                    continue
        finally:
            try:
                s.close()
            except Exception:
                pass
            print(f"[{self.proc_id}] servidor parado")
    
    def _handle_connection(self, conn):
        """Lidar com conexão de entrada e processar mensagem recebida."""
        try:
            data = conn.recv(4096)
            if data:
                message_data = json.loads(data.decode())
                message = Message.from_dict(message_data)
                self._process_received_message(message)
        except Exception as e:
            print(f"[{self.proc_id}] Erro ao lidar com conexão: {e}")
        finally:
            conn.close()

    def _process_received_message(self, message):
        """
        Process a received message, either REQUEST or REPLY for Ricart-Agrawala algorithm.
        """
        if message.msg_type == MessageType.REQUEST:
            self.update_clock_on_receive(message.logical_time)
            
            print(f"[{self.proc_id}] Received REQUEST from {message.sender} for resource '{message.resource_name}' (ts:{message.logical_time})")
            
            self.process_request(message)
            
        elif message.msg_type == MessageType.REPLY:
            self.update_clock_on_receive(message.logical_time)
            
            print(f"[{self.proc_id}] Received REPLY from {message.sender} (ts:{message.logical_time})")
            self.process_reply(message)
            
        else:
            print(f"[{self.proc_id}] Warning: Received unknown message type: {message.msg_type}")
        
    def increment_clock(self):
        """Antes de executar um evento, incrementar Ci."""
        with self.clock_lock:
            old_clock = self.logical_clock
            self.logical_clock += self.clock_increment
            print(f"[{self.proc_id}] Relógio incrementado: {old_clock} → {self.logical_clock}")
            return self.logical_clock
    
    def update_clock_on_receive(self, received_timestamp):
        """ Ao receber a mensagem m, ajustar Cj = max{Cj, ts(m)}. + 1"""
        with self.clock_lock:
            old_clock = self.logical_clock
            self.logical_clock = max(self.logical_clock, received_timestamp) + 1
            if self.logical_clock != old_clock:
                print(f"[{self.proc_id}] Relógio ajustado no recebimento: {old_clock} → {self.logical_clock} (timestamp recebido: {received_timestamp})")
            else:
                print(f"[{self.proc_id}] Relógio inalterado no recebimento: {self.logical_clock} (timestamp recebido: {received_timestamp})")
    
    def get_clock(self):
        """Obter valor atual do relógio lógico."""
        with self.clock_lock:
            return self.logical_clock

    def stop(self):
        """Parar o processo."""
        self._running.clear()
        try:
            if self._server_socket:
                self._server_socket.close()
        except Exception:
            pass
