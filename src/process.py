import socket
import threading
import json
import time
from message import Message, MessageType

HOST = "localhost"

class ResourceState:
    RELEASED = "released"
    WANTED = "wanted"
    HELD = "held"

class Process:
    def __init__(self, proc_id: str, port: int, other_ports: list, clock_increment: int = 1):
        self.proc_id = proc_id
        self.port = port
        self.other_ports = other_ports
        self.clock_increment = clock_increment
        self.logical_clock = 0
        self.clock_lock = threading.Lock()
        self._server_socket = None
        self._running = threading.Event()
        self.all_ports = sorted([port] + other_ports) 
        port_to_process = {5000: "processo1", 5001: "processo2", 5002: "processo3"}
        self.all_processes = set([port_to_process[p] for p in self.all_ports])
        self.total_processes = len(self.all_processes)
        print(f"[{self.proc_id}] Processos: {sorted(list(self.all_processes))}")
        self.resource_states = {}
        self.resource_lock = threading.Lock()
        self.pending_requests = {}  
        self.request_lock = threading.Lock()
        self.request_queue = [] 
        self.queue_lock = threading.Lock()
        self.my_request_timestamps = {} 
        self.timestamp_lock = threading.Lock()
    
    def request_resource(self, resource_name: str):
        print(f"\n[{self.proc_id}] Solicitando recurso '{resource_name}'")
        current_state = self.get_resource_state(resource_name)
        if current_state == ResourceState.HELD:
            print(f"[{self.proc_id}] Já possui '{resource_name}'")
            return
        if current_state == ResourceState.WANTED:
            print(f"[{self.proc_id}] Já está aguardando '{resource_name}'")
            return
        timestamp = self.increment_clock()
        with self.resource_lock:
            self.resource_states[resource_name] = ResourceState.WANTED
        with self.timestamp_lock:
            self.my_request_timestamps[resource_name] = timestamp
        request_msg = Message.create_request(self.proc_id, timestamp, resource_name)
        with self.request_lock:
            self.pending_requests[resource_name] = {"request_msg": request_msg, "replies_received": set()}
        print(f"[{self.proc_id}] REQUEST enviado (ts: {timestamp})")
        self._multicast_message(request_msg)
        print(f"[{self.proc_id}] Aguardando {len(self.all_processes)-1} GRANTs...")

    def process_request(self, message: Message):
        print(f"[{self.proc_id}] REQUEST de {message.sender} para '{message.resource_name}' (ts:{message.logical_time})")
        current_state = self.get_resource_state(message.resource_name)
        if current_state == ResourceState.RELEASED:
            self.send_reply(message.sender, message.msg_id, True)
            return
        if current_state == ResourceState.HELD:
            self.queue_request(message)
            self.send_reply(message.sender, message.msg_id, False)
            return
        if current_state == ResourceState.WANTED:
            with self.timestamp_lock:
                my_timestamp = self.my_request_timestamps.get(message.resource_name, float('inf'))
            if (message.logical_time < my_timestamp) or \
               (message.logical_time == my_timestamp and message.sender < self.proc_id):
                self.send_reply(message.sender, message.msg_id, True)
            else:
                self.queue_request(message)
                self.send_reply(message.sender, message.msg_id, False)

    def process_reply(self, message: Message):
        print(f"[{self.proc_id}] REPLY de {message.sender} (granted={message.granted})")
        with self.request_lock:
            resource_found = None
            for resource_name, pending in self.pending_requests.items():
                if pending["request_msg"].msg_id == message.request_id:
                    resource_found = resource_name
                    break
            if not resource_found: return
            if not message.granted: return
            self.pending_requests[resource_found]["replies_received"].add(message.sender)
            replies_count = len(self.pending_requests[resource_found]["replies_received"])
            needed_replies = len(self.all_processes) - 1
            print(f"[{self.proc_id}] {replies_count}/{needed_replies} GRANTs para '{resource_found}'")
            if replies_count >= needed_replies:
                del self.pending_requests[resource_found]
                self.enter_critical_section(resource_found)

    def send_reply(self, to_process: str, request_id: str, granted: bool = True):
        timestamp = self.increment_clock()
        reply_msg = Message.create_reply(self.proc_id, timestamp, request_id, granted)
        process_to_port = {"processo1": 5000, "processo2": 5001, "processo3": 5002}
        target_port = process_to_port.get(to_process)
        if target_port:
            action = "GRANT" if granted else "DEFER"
            print(f"[{self.proc_id}] REPLY {action} → {to_process}")
            self._send_message_to_port(reply_msg, target_port)

    def enter_critical_section(self, resource_name: str):
        print(f"\n[{self.proc_id}] Entrando na seção crítica '{resource_name}'")
        with self.resource_lock:
            self.resource_states[resource_name] = ResourceState.HELD
        with self.timestamp_lock:
            self.my_request_timestamps.pop(resource_name, None)
        print(f"[{self.proc_id}] Acesso exclusivo '{resource_name}' obtido")

    def exit_critical_section(self, resource_name: str):
        current_state = self.get_resource_state(resource_name)
        if current_state != ResourceState.HELD:
            print(f"[{self.proc_id}] Não possui '{resource_name}'")
            return
        print(f"\n[{self.proc_id}] Liberando '{resource_name}'")
        with self.resource_lock:
            self.resource_states[resource_name] = ResourceState.RELEASED
        self.process_queued_requests(resource_name)

    def _proc_number(self, sender: str):
        digits = ''.join(ch for ch in str(sender) if ch.isdigit())
        return int(digits) if digits else sender

    def queue_request(self, message: Message):
        with self.queue_lock:
            key_new = (message.logical_time, self._proc_number(message.sender))
            same_idxs = [i for i, r in enumerate(self.request_queue) if r.resource_name == message.resource_name]
            if not same_idxs:
                self.request_queue.append(message)
                print(f"[{self.proc_id}] Requisição de {message.sender} enfileirada")
                return
            start, end = same_idxs[0], same_idxs[-1] + 1
            inserted = False
            for idx in range(start, end):
                r = self.request_queue[idx]
                key_r = (r.logical_time, self._proc_number(r.sender))
                if key_new < key_r:
                    self.request_queue.insert(idx, message)
                    inserted = True
                    break
            if not inserted:
                self.request_queue.insert(end, message)
            print(f"[{self.proc_id}] Requisição de {message.sender} enfileirada (ordenada)")

    def process_queued_requests(self, released_resource: str):
        with self.queue_lock:
            for i, req in enumerate(self.request_queue):
                if req.resource_name == released_resource:
                    top = self.request_queue.pop(i)
                    print(f"[{self.proc_id}] Processando fila '{released_resource}' → GRANT {top.sender}")
                    self.send_reply(top.sender, top.msg_id, True)
                    return

    def get_resource_state(self, resource_name):
        resource_name = str(resource_name)
        with self.resource_lock:
            return self.resource_states.get(resource_name, ResourceState.RELEASED)

    def show_queue(self):
        with self.queue_lock:
            if not self.request_queue:
                print(f"[{self.proc_id}] Fila vazia")
            else:
                print(f"[{self.proc_id}] Fila ({len(self.request_queue)}):")
                for i, req in enumerate(self.request_queue):
                    print(f"  {i+1}. {req.sender} -> '{req.resource_name}' (ts:{req.logical_time})")
    
    def show_status(self):
        print(f"\n[{self.proc_id}] STATUS")
        print(f"Clock: {self.get_clock()}")
        resources = [str(i) for i in range(1, 2)]  
        for resource in resources:
            state = self.get_resource_state(resource)
            print(f"  Recurso {resource}: {state}")
        with self.request_lock:
            if self.pending_requests:
                print("Pendentes:")
                for resource, data in self.pending_requests.items():
                    replies_count = len(data["replies_received"])
                    needed = len(self.all_processes) - 1
                    print(f"  {resource}: {replies_count}/{needed} GRANTs")
            else:
                print("Nenhuma requisição pendente")
        with self.queue_lock:
            if self.request_queue:
                print(f"Fila recebida ({len(self.request_queue)}):")
                for i, req in enumerate(self.request_queue):
                    print(f"  {i+1}. {req.sender} -> '{req.resource_name}' (ts:{req.logical_time})")
            else:
                print("Fila recebida vazia")
        print("=" * 30)

    def _multicast_message(self, message: Message):
        for port in self.other_ports:
            self._send_message_to_port(message, port)

    def _send_message_to_port(self, message: Message, port: int):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((HOST, port))
                s.send(json.dumps(message.to_dict()).encode())
                print(f"[{self.proc_id}] → {message.msg_type.value.upper()} para porta {port}")
        except Exception as e:
            print(f"[{self.proc_id}] Erro porta {port}: {e}")

    def start(self):
        self._running.set()
        t = threading.Thread(target=self._serve, daemon=True)
        t.start()
    
    def _serve(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, self.port))
        s.listen(5)
        self._server_socket = s
        print(f"[{self.proc_id}] Escutando {HOST}:{self.port}")
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
            print(f"[{self.proc_id}] Servidor parado")
    
    def _handle_connection(self, conn):
        try:
            data = conn.recv(4096)
            if data:
                message_data = json.loads(data.decode())
                message = Message.from_dict(message_data)
                self._process_received_message(message)
        except Exception as e:
            print(f"[{self.proc_id}] Erro conexão: {e}")
        finally:
            conn.close()

    def _process_received_message(self, message):
        if message.msg_type == MessageType.REQUEST:
            self.update_clock_on_receive(message.logical_time)
            self.process_request(message)
        elif message.msg_type == MessageType.REPLY:
            self.update_clock_on_receive(message.logical_time)
            self.process_reply(message)
        else:
            print(f"[{self.proc_id}] Tipo de mensagem desconhecido: {message.msg_type}")
        
    def increment_clock(self):
        with self.clock_lock:
            old_clock = self.logical_clock
            self.logical_clock += self.clock_increment
            print(f"[{self.proc_id}] Clock {old_clock} → {self.logical_clock}")
            return self.logical_clock
    
    def update_clock_on_receive(self, received_timestamp):
        with self.clock_lock:
            old_clock = self.logical_clock
            self.logical_clock = max(self.logical_clock, received_timestamp) + 1
            if self.logical_clock != old_clock:
                print(f"[{self.proc_id}] Clock ajustado {old_clock} → {self.logical_clock} (recv:{received_timestamp})")
    
    def get_clock(self):
        with self.clock_lock:
            return self.logical_clock

    def stop(self):
        self._running.clear()
        try:
            if self._server_socket:
                self._server_socket.close()
        except Exception:
            pass
