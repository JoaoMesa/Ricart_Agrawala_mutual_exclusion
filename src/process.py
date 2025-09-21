# process.py
import socket
import threading
import json
import time
from message import Message, MessageType

HOST = "localhost"

class Process:
    """Processo com relógio lógico e capacidades de multicast totalmente ordenado."""
    
    def __init__(self, proc_id: str, port: int, other_ports: list, clock_increment: int = 1):
        self.proc_id = proc_id
        self.port = port
        self.other_ports = other_ports
        self.clock_increment = clock_increment
        
        # Relógio lógico de Lamport
        self.logical_clock = 0
        self.clock_lock = threading.Lock()
        
        # Fila de mensagens ordenadas por timestamp
        self.message_queue = []
        self.queue_lock = threading.Lock()
        
        # Rastreamento de confirmações (acks)
        # Mantém registro de quais processos confirmaram cada mensagem
        self.acknowledgments = {}
        self.ack_lock = threading.Lock()
        
        # Socket do servidor
        self._server_socket = None
        self._running = threading.Event()
        
        # Todos os processos no grupo 
        self.all_ports = sorted([port] + other_ports) 
        port_to_process = {5000: "processo1", 5001: "processo2", 5002: "processo3"}
        self.all_processes = set([port_to_process[p] for p in self.all_ports])
        self.required_acks = len(self.all_processes)  # Precisa de confirmações de todos os processos
        
        print(f"[{self.proc_id}] Todos os processos no grupo: {sorted(list(self.all_processes))}")
        print(f"[{self.proc_id}] Confirmações necessárias: {self.required_acks}")
        
        # Se o ack chega antes da mensagem, armazenamos o ack pendente até que a mensagem original chegue
        self.pending_acks = {}  # {message_id: lista de mensagens de confirmação}
        self.pending_lock = threading.Lock()
    
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
        Processar uma mensagem recebida, seja multicast ou confirmação (ack).
        """
        if message.msg_type == MessageType.MULTICAST:
            #Ao receber, ajustar Cj = max{Cj, ts(m)} + 1
            self.update_clock_on_receive(message.timestamp)
            
            # Adicionar à fila ordenada por timestamp, depois por remetente para quebra de empate
            with self.queue_lock:
                self.message_queue.append(message)
                self.message_queue.sort(key=lambda m: (m.timestamp, m.sender))
            
            print(f"[{self.proc_id}] Recebido multicast de {message.sender}: '{message.content}' (ts:{message.timestamp})")
            
            # Inicializar rastreamento de confirmação
            with self.ack_lock:
                self.acknowledgments[message.msg_id] = set()
            
            # Processar quaisquer confirmações pendentes para esta mensagem
            # Isso lida com o cenário onde acks chegaram antes da mensagem original
            with self.pending_lock:
                if message.msg_id in self.pending_acks:
                    pending_ack_messages = self.pending_acks[message.msg_id]
                    del self.pending_acks[message.msg_id]
                    for ack_msg in pending_ack_messages:
                        self._process_acknowledgment(ack_msg)
            
            # Enviar confirmação para todos os outros processos
            threading.Timer(0.01, self._send_acknowledgment, args=(message,)).start()
            
        elif message.msg_type == MessageType.ACK:
            self._process_acknowledgment(message)
    
    def _process_acknowledgment(self, message):
        """Processar uma mensagem de confirmação."""
        # Ao receber, ajustar Cj = max{Cj, ts(m)} + 1
        self.update_clock_on_receive(message.timestamp)
        
        
        # Verificar se temos a mensagem original
        with self.ack_lock:
            if message.original_msg_id in self.acknowledgments:
                # Temos a mensagem original, registrar a confirmação
                self.acknowledgments[message.original_msg_id].add(message.sender)
                print(f"[{self.proc_id}] Recebida confirmação de {message.sender} para mensagem {message.original_msg_id}")
            else:
                # Mensagem original ainda não recebida
                # Armazenamos a confirmação como pendente até que a mensagem original chegue
                with self.pending_lock:
                    if message.original_msg_id not in self.pending_acks:
                        self.pending_acks[message.original_msg_id] = []
                    self.pending_acks[message.original_msg_id].append(message)
                    print(f"[{self.proc_id}] Recebida confirmação de {message.sender} para mensagem {message.original_msg_id} (pendente - mensagem original ainda não recebida)")
    
    def _send_acknowledgment(self, original_message):
        """Enviar confirmação para uma mensagem recebida."""
        #  Antes de executar evento (enviar), incrementar Ci
        current_time = self.increment_clock()
        
        # Definir timestamp da mensagem para Ci (após passo 1)
        ack_message = Message(
            msg_type=MessageType.ACK,
            sender=self.proc_id,
            timestamp=current_time,
            original_msg_id=original_message.msg_id
        )
        
        print(f"[{self.proc_id}] Enviando confirmação para mensagem de {original_message.sender} (ts:{current_time})")
        
        # Enviar confirmação para todos os processos no grupo
        self._broadcast_message(ack_message)
    
    def try_deliver_message(self):
        """
        Tentar entregar a próxima mensagem da fila (entrega manual).
        
        REGRA DE MULTICAST TOTALMENTE ORDENADO: 
        - Só pode entregar a mensagem do INÍCIO da fila
        - E somente se foi confirmada por TODOS os processos do grupo
        """
        with self.queue_lock:
            if not self.message_queue:
                print(f"[{self.proc_id}] Nenhuma mensagem na fila para entregar")
                return False
            
            #  Somente verificar o INÍCIO da fila (índice 0)
            head_message = self.message_queue[0]
            
            # Verificar se esta mensagem do INÍCIO foi confirmada por todos os processos
            with self.ack_lock:
                if head_message.msg_id in self.acknowledgments:
                    acked_by = self.acknowledgments[head_message.msg_id]
                    acks_received = len(acked_by)
                    
                    print(f"[{self.proc_id}] Verificando mensagem do INÍCIO '{head_message.content}' de {head_message.sender}")
                    print(f"[{self.proc_id}] Confirmações: {acks_received}/{self.required_acks}")
                    print(f"[{self.proc_id}] Confirmado por: {sorted(list(acked_by))}")
                    
                    if acks_received >= self.required_acks:
                        # Mensagem do INÍCIO pode ser entregue - remover da fila
                        delivered_message = self.message_queue.pop(0)
                        del self.acknowledgments[head_message.msg_id]
                        self._deliver_message(delivered_message)
                        return True
                    else:
                        print(f"[{self.proc_id}] Não é possível entregar mensagem do INÍCIO: necessita de mais {self.required_acks - acks_received} confirmações")
                        return False
                else:
                    print(f"[{self.proc_id}] Não é possível entregar mensagem do INÍCIO: nenhuma confirmação recebida ainda")
                    return False
    
    def _deliver_message(self, message):
        """Entregar uma mensagem para a aplicação."""
        print(f"[{self.proc_id}] ✓ ENTREGANDO MENSAGEM: '{message.content}' de {message.sender} (ts:{message.timestamp})")
        print(f"[{self.proc_id}] Mensagem processada pela aplicação")
    
    def send_message(self, content):
        """Enviar uma mensagem usando multicast totalmente ordenado."""
        # Antes de executar evento (enviar), incrementar Ci
        current_time = self.increment_clock()
        
        # Definir timestamp da mensagem para Ci (após passo 1)
        message = Message(
            msg_type=MessageType.MULTICAST,
            content=content,
            sender=self.proc_id,
            timestamp=current_time
        )
        
        print(f"[{self.proc_id}] Enviando multicast: '{content}' (ts:{current_time})")
        
        # Inicializar rastreamento de confirmação
        with self.ack_lock:
            self.acknowledgments[message.msg_id] = set()
        
        # Transmitir para todos os processos 
        # A mensagem será enfileirada quando a recebermos de volta
        self._broadcast_message(message)
    
    def _broadcast_message(self, message):
        """Transmitir uma mensagem para todos os processos no grupo."""
        message_data = json.dumps(message.to_dict()).encode()
        
        for port in self.all_ports:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.connect((HOST, port))
                s.send(message_data)
                s.close()
            except Exception as e:
                print(f"[{self.proc_id}] Falha ao enviar para porta {port}: {e}")
    
    def show_queue(self):
        """Exibir fila de mensagens atual com regras de multicast totalmente ordenado."""
        with self.queue_lock:
            if not self.message_queue:
                print(f"[{self.proc_id}] Fila de mensagens está vazia")
            else:
                print(f"[{self.proc_id}] Fila de mensagens ({len(self.message_queue)} mensagens):")
                for i, msg in enumerate(self.message_queue):
                    with self.ack_lock:
                        acks = len(self.acknowledgments.get(msg.msg_id, set()))
                        needed = self.required_acks
                        acked_by = self.acknowledgments.get(msg.msg_id, set())
                    
                    # Somente a mensagem do INÍCIO (i == 0) pode ser entregável em multicast totalmente ordenado
                    is_head = (i == 0)
                    is_fully_acked = (acks >= needed)
                    deliverable = " (ENTREGÁVEL)" if is_head and is_fully_acked else ""
                    head_indicator = " [INÍCIO]" if is_head else ""
                    blocked_reason = ""
                    
                    if not is_head and is_fully_acked:
                        blocked_reason = " (bloqueada: não está no início)"
                    elif is_head and not is_fully_acked:
                        blocked_reason = f" (bloqueada: necessita de mais {needed - acks} confirmações)"
                    
                    print(f"  {i+1}. '{msg.content}' de {msg.sender} (ts:{msg.timestamp}) - {acks}/{needed} confirmações{deliverable}{head_indicator}{blocked_reason}")
                    if acked_by:
                        print(f"      Confirmado por: {sorted(list(acked_by))}")
                
                # Mostrar confirmações pendentes (acks que chegaram antes das mensagens originais)
                with self.pending_lock:
                    if self.pending_acks:
                        print(f"\n[{self.proc_id}] Confirmações pendentes (recebidas antes da mensagem original):")
                        for msg_id, ack_list in self.pending_acks.items():
                            senders = [ack.sender for ack in ack_list]
                            print(f"  Mensagem {msg_id}: Confirmações de {senders}")
                
                
                if self.message_queue:
                    head_msg = self.message_queue[0]
                    with self.ack_lock:
                        head_acks = len(self.acknowledgments.get(head_msg.msg_id, set()))
                    
                    print(f"\n[{self.proc_id}] Status do Multicast Totalmente Ordenado:")
                    if head_acks >= self.required_acks:
                        print(f"  ✓ Mensagem do INÍCIO pode ser entregue")
                    else:
                        print(f"  ✗ Mensagem do INÍCIO necessita de mais {self.required_acks - head_acks} confirmações")
                        print(f"  ✗ Todas as outras mensagens bloqueadas até que a do INÍCIO seja entregue")
    
    def stop(self):
        """Parar o processo."""
        self._running.clear()
        try:
            if self._server_socket:
                self._server_socket.close()
        except Exception:
            pass