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
        self.total_processes = len(self.all_processes)  # Need replies from all processes
        
        print(f"[{self.proc_id}] All processes in group: {sorted(list(self.all_processes))}")
        print(f"[{self.proc_id}] Total processes: {self.total_processes}")
        
        # === RICART-AGRAWALA SPECIFIC DATA STRUCTURES ===
        
        # Resource states: tracks state for each resource
        self.resource_states = {}  # {resource_name: ResourceState}
        self.resource_lock = threading.Lock()
        
        # Current requests: tracks our own requests waiting for replies
        self.pending_requests = {}  # {resource_name: {"request_msg": Message, "replies_received": set}}
        self.request_lock = threading.Lock()
        
        # Request queue: stores requests from other processes that we can't reply to yet
        self.request_queue = []  # List of Message objects
        self.queue_lock = threading.Lock()
        
        # Current request being processed (for timestamp comparison)
        self.current_request = {}  # {resource_name: Message}
        self.current_lock = threading.Lock()
    
    def request_resource(self, resource_name: str):
        """
        Solicita acesso a um recurso usando o algoritmo Ricart-Agrawala.
        Versão inicial: sempre recebe permissão.
        """
        print(f"\n[{self.proc_id}] === SOLICITANDO RECURSO '{resource_name}' ===")
        
        # Verifica se já está usando o recurso
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
        
        # Cria mensagem de REQUEST
        request_msg = Message.create_request(
            sender=self.proc_id,
            logical_time=timestamp,
            resource_name=resource_name
        )
        
        # Armazena nossa requisição atual
        with self.current_lock:
            self.current_request[resource_name] = request_msg
        
        # Inicializa contador de respostas
        with self.request_lock:
            self.pending_requests[resource_name] = {
                "request_msg": request_msg,
                "replies_received": set()
            }
        
        print(f"[{self.proc_id}] Enviando REQUEST para todos os processos (ts: {timestamp})")
        
        # Envia REQUEST para todos os outros processos
        self._multicast_message(request_msg)
        
        print(f"[{self.proc_id}] Aguardando respostas de {len(self.all_processes) - 1} processos...")

    def process_request(self, message: Message):
        """
        Processa uma mensagem REQUEST recebida.
        Versão inicial: sempre responde com OK imediatamente.
        """
        print(f"[{self.proc_id}] Processando REQUEST de {message.sender} para '{message.resource_name}'")
        
        # Versão inicial: sempre envia REPLY (OK) imediatamente
        print(f"[{self.proc_id}] → Enviando REPLY (OK) para {message.sender}")
        self.send_reply(message.sender, message.msg_id)

    def process_reply(self, message: Message):
        """
        Processa uma mensagem REPLY (OK) recebida.
        """
        print(f"[{self.proc_id}] Processando REPLY de {message.sender}")
        
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
            
            # Adiciona o remetente ao conjunto de respostas recebidas
            self.pending_requests[resource_found]["replies_received"].add(message.sender)
            replies_count = len(self.pending_requests[resource_found]["replies_received"])
            needed_replies = len(self.all_processes) - 1  # Exceto nós mesmos
            
            print(f"[{self.proc_id}] REPLY {replies_count}/{needed_replies} recebido para '{resource_found}'")
            
            # Verifica se recebemos todas as respostas necessárias
            if replies_count >= needed_replies:
                print(f"[{self.proc_id}] ✓ Todas as respostas recebidas para '{resource_found}'!")
                
                # Remove da lista de requisições pendentes
                del self.pending_requests[resource_found]
                
                # Entra na seção crítica
                self.enter_critical_section(resource_found)

    def send_reply(self, to_process: str, request_id: str):
        """
        Envia uma mensagem REPLY (OK) para um processo.
        """
        timestamp = self.increment_clock()
        
        reply_msg = Message.create_reply(
            sender=self.proc_id,
            logical_time=timestamp,
            request_id=request_id
        )
        
        # Encontra a porta do processo de destino
        process_to_port = {"processo1": 5000, "processo2": 5001, "processo3": 5002}
        target_port = process_to_port.get(to_process)
        
        if target_port is None:
            print(f"[{self.proc_id}] Erro: processo desconhecido '{to_process}'")
            return
        
        self._send_message_to_port(reply_msg, target_port)

    def enter_critical_section(self, resource_name: str):
        """
        Entra na seção crítica (obtém acesso exclusivo ao recurso).
        """
        print(f"\n[{self.proc_id}] 🔒 ENTRANDO NA SEÇÃO CRÍTICA - Recurso '{resource_name}'")
        
        with self.resource_lock:
            self.resource_states[resource_name] = ResourceState.HELD
        
        with self.current_lock:
            if resource_name in self.current_request:
                del self.current_request[resource_name]
        
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
        
        # Processa requisições enfileiradas (por enquanto, lista vazia)
        self.process_queued_requests()
        
        print(f"[{self.proc_id}] ✓ Recurso '{resource_name}' liberado!")

    def compare_requests(self, req1: Message, req2: Message):
        """
        Compara duas requisições para determinar prioridade.
        Retorna True se req1 tem prioridade sobre req2.
        """
        # Prioridade por timestamp (menor = maior prioridade)
        if req1.logical_time != req2.logical_time:
            return req1.logical_time < req2.logical_time
        
        # Em caso de empate, usa ID do processo (ordem lexicográfica)
        return req1.sender < req2.sender

    def queue_request(self, message: Message):
        """
        Enfileira uma requisição para processar mais tarde.
        """
        with self.queue_lock:
            self.request_queue.append(message)
            print(f"[{self.proc_id}] Requisição de {message.sender} enfileirada")

    def process_queued_requests(self):
        """
        Processa requisições enfileiradas após liberar um recurso.
        Por enquanto, não há requisições enfileiradas (sempre respondemos OK).
        """
        with self.queue_lock:
            if self.request_queue:
                print(f"[{self.proc_id}] Processando {len(self.request_queue)} requisições enfileiradas")
                # Por enquanto, não fazemos nada pois sempre respondemos OK imediatamente
            else:
                print(f"[{self.proc_id}] Nenhuma requisição enfileirada para processar")

    def get_resource_state(self, resource_name):
        """
        Retorna o estado atual de um recurso.
        """
        # Garantir que resource_name seja sempre string
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
            # Update logical clock: Cj = max{Cj, ts(m)} + 1
            self.update_clock_on_receive(message.logical_time)
            
            print(f"[{self.proc_id}] Received REQUEST from {message.sender} for resource '{message.resource_name}' (ts:{message.logical_time})")
            
            # Process the resource request using the 3-case decision logic
            self.process_request(message)
            
        elif message.msg_type == MessageType.REPLY:
            # Update logical clock: Cj = max{Cj, ts(m)} + 1  
            self.update_clock_on_receive(message.logical_time)
            
            print(f"[{self.proc_id}] Received REPLY from {message.sender} (ts:{message.logical_time})")
            
            # Process the reply (OK message) 
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