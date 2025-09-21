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
        pass 

    def process_request(self, message: Message):
        pass

    def process_reply(self, message: Message):
        pass

    def send_reply(self, to_process: str, request_id: str):
        pass

    def enter_critical_section(self, resource_name: str):
        pass

    def exit_critical_section(self, resource_name: str):
        pass

    def compare_requests(self, req1: Message, req2: Message):
        pass

    def queue_request(self, message: Message):
        pass

    def process_queued_requests(self):
        pass

    def get_resource_state(self, resource_name: str):
        pass


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