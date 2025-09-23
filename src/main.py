# main.py
import socket
import sys
from process import Process

HOST = "localhost"
PORTS = [5000, 5001, 5002]
PROC_NAMES = {5000: "processo1", 5001: "processo2", 5002: "processo3"}
RESOURCES = [str(i) for i in range(1, 2)]  # Recursos como strings
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
        clock_increment = int(input(f"Escolha o incremento de clock para {proc_id} (padrão 1): ") or "1")
        if clock_increment <= 0:
            clock_increment = 1
    except ValueError:
        clock_increment = 1
    
    other_ports = [p for p in PORTS if p != chosen]
    
    proc = Process(proc_id, chosen, other_ports, clock_increment)
    proc.start()
    
    try:
        print(f"\nIniciando processo {proc_id}, porta {chosen} com incremento de clock {clock_increment}.")
        print("\n" + "="*50)
        print("ALGORITMO RICART-AGRAWALA - EXCLUSÃO MÚTUA DISTRIBUÍDA")
        print("="*50)
        print("\nComandos disponíveis:")
        print("  request <resource>  - Faz uma requisição pelo recurso")
        print("  release <resource>  - Libera o recurso (sai da seção crítica)")
        print("  status              - Mostra status completo do processo")
        print("  queue               - Mostra apenas a fila de pedidos recebidos")
        print("  clock               - Mostra o clock lógico atual")
        print("  pass                - Incrementa o relógio em um ciclo")
        print("  quit                - Para o processo")
        print(f"\nRecursos disponíveis: {', '.join(RESOURCES)}")
        print("="*50)
        
        while True:
            try:
                user_input = input(f"\n[{proc_id}]> ").strip()
                if not user_input:
                    continue
                
                cmd_parts = user_input.split()
                cmd = cmd_parts[0].lower()

                if cmd == "quit" or cmd == "exit":
                    print("Encerrando processo...")
                    break
                    
                elif cmd == "status":
                    proc.show_status()
                    
                elif cmd == "queue":
                    proc.show_queue()
                    
                elif cmd == "clock":
                    print(f"Clock lógico atual: {proc.get_clock()}")
                    
                elif cmd == "pass":
                    old_clock = proc.get_clock()
                    new_clock = proc.increment_clock()
                    print(f"Clock avançado: {old_clock} → {new_clock}")
                    
                elif cmd == "request":
                    if len(cmd_parts) < 2:
                        print("Uso: request <resource>")
                        print(f"Recursos disponíveis: {', '.join(RESOURCES)}")
                        continue
                    resource = cmd_parts[1]
                    if resource not in RESOURCES:
                        print(f"Recurso '{resource}' não existe!")
                        print(f"Recursos disponíveis: {', '.join(RESOURCES)}")
                        continue
                    proc.request_resource(resource)
                    
                elif cmd == "release":
                    if len(cmd_parts) < 2:
                        print("Uso: release <resource>")
                        print(f"Recursos disponíveis: {', '.join(RESOURCES)}")
                        continue
                    resource = cmd_parts[1]
                    if resource not in RESOURCES:
                        print(f"Recurso '{resource}' não existe!")
                        print(f"Recursos disponíveis: {', '.join(RESOURCES)}")
                        continue
                    proc.exit_critical_section(resource)
                    
                else:
                    print(f"Comando '{cmd}' não reconhecido. Digite 'help' para ver os comandos disponíveis.")
                    
            except KeyboardInterrupt:
                print("\n\nInterrupção detectada. Encerrando processo...")
                break
            except Exception as e:
                print(f"Erro ao processar comando: {e}")
                
    finally:
        proc.stop()
        print("Processo finalizado.")

if __name__ == "__main__":
    main()