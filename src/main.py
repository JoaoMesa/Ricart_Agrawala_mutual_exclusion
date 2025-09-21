###############
#   Atividade de Sistemas Distribuídos
#   Exclusão Mútua: Ricart & Agrawala
#   João Vitor Naves Mesa - 814149
#   Vinicius Fernandes Terra Silva - 814146
#
################

# main.py
import socket
import sys
from process import Process

HOST = "localhost"
PORTS = [5000, 5001, 5002]
PROC_NAMES = {5000: "processo1", 5001: "processo2", 5002: "processo3"}

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
        print("  send <message>  - Envia a mensagem")
        print("  queue          - Mostra a fila de mensagens atual")
        print("  deliver        - Tenta entregar a mensagem que está no iníci da fila")
        print("  clock          - Mostra o clock atual")
        print("  pass           - Incrementa o relógio em um ciclo")
        print("  quit           - Para o processo")
        
        while True:
            try:
                user_input = input(f"[{proc_id}]> ").strip()
                if not user_input:
                    continue
                    
                if user_input.lower() == "quit":
                    break
                elif user_input.lower() == "deliver":
                    proc.try_deliver_message()
                elif user_input.lower() == "queue":
                    proc.show_queue()
                elif user_input.lower() == "clock":
                    print(f"Clock atual: {proc.get_clock()}")
                elif user_input.lower() == "pass":
                    proc.increment_clock()
                elif user_input.startswith("send "):
                    message_content = user_input[5:].strip()
                    if message_content:
                        proc.send_message(message_content)
                    else:
                        print("Falta o conteúdo da mensagem.")
                else:
                    print("Comando inválido.")
                    
            except KeyboardInterrupt:
                break
                
    finally:
        proc.stop()
        print("Processo interropido.")

if __name__ == "__main__":
    main()