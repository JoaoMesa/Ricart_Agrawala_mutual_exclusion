# === main.py ===
import socket
import sys
from process import Process

HOST = "localhost"
PORTS = [5000, 5001, 5002]
PROC_NAMES = {5000: "processo1", 5001: "processo2", 5002: "processo3"}
RESOURCES  = [i for i in range(1, 6)]
print("Recursos disponíveis:", RESOURCES)


def pick_free_port(candidates):
    for p in candidates:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((HOST, p))
            s.close()
            return p
        except OSError:
            s.close()
            continue
    return None


def main():
    chosen = pick_free_port(PORTS)
    if chosen is None:
        print("Nenhuma porta disponível entre:", PORTS)
        sys.exit(1)
    
    proc_id = PROC_NAMES[chosen]
    
    # Ask user for clock increment
    try:
        clock_increment = int(input(f"Escolha o incremento de clock {proc_id} (padrão 1): ") or "1")
        if clock_increment <= 0:
            clock_increment = 1
    except ValueError:
        clock_increment = 1
    
    other_ports = [p for p in PORTS if p != chosen]
    
    proc = Process(proc_id, chosen, other_ports, clock_increment)
    proc.start()
    
    try:
        print(f"Iniciando processo {proc_id}, porta {chosen} com incremento de clock {clock_increment}.")
        print("\nComandos:")
        print("  request <resource>  - Faz uma requisição pelo recurso")
        print("  release <resource>  - Libera o recurso (sai da seção crítica)")
        print("  status              - Mostra estado dos recursos locais")
        print("  queue               - Mostra a fila de pedidos recebidos")
        print("  clock               - Mostra o clock atual")
        print("  pass                - Incrementa o relógio em um ciclo")
        print("  quit                - Para o processo")
        
        while True:
            try:
                user_input = input(f"[{proc_id}]> ").strip()
                if not user_input:
                    continue
                
                cmd_parts = user_input.split()
                cmd = cmd_parts[0].lower()

                if cmd == "quit":
                    break
                elif cmd == "status":
                    # Simple status print (process.py provides get_resource_state stub)
                    for r in RESOURCES:
                        st = proc.get_resource_state(r)
                        print(f"Recurso {r}: {st}")
                elif cmd == "queue":
                    proc.show_queue()
                elif cmd == "clock":
                    print(f"Clock atual: {proc.get_clock()}")
                elif cmd == "pass":
                    proc.increment_clock()
                elif cmd == "request":
                    if len(cmd_parts) < 2:
                        print("Uso: request <resource>")
                        continue
                    resource = cmd_parts[1]
                    proc.request_resource(resource)
                elif cmd == "release":
                    if len(cmd_parts) < 2:
                        print("Uso: release <resource>")
                        continue
                    resource = cmd_parts[1]
                    proc.exit_critical_section(resource)
                else:
                    print("Comando inválido.")
                    
            except KeyboardInterrupt:
                break
                
    finally:
        proc.stop()
        print("Processo interrompido.")

if __name__ == "__main__":
    main()


