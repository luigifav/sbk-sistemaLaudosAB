"""
tunel.py
Abre um tunel publico para o sistema de laudos.
Rode DEPOIS de iniciar o servidor.py em outro PowerShell.

Uso: python tunel.py
"""
from pyngrok import ngrok
import time

print("\n  Abrindo tunel...")
print("  (O servidor precisa estar rodando em outro PowerShell)\n")

# Abrir tunel na porta 8080
tunel = ngrok.connect(8080, "http")

print("=" * 55)
print(f"  LINK DE ACESSO: {tunel.public_url}")
print("=" * 55)
print("\n  Compartilhe esse link com o time.")
print("  O link muda toda vez que reiniciar este script.")
print("\n  Pressione Ctrl+C para encerrar o tunel.\n")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n  Tunel encerrado.")
    ngrok.kill()
