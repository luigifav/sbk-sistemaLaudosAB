# Sistema de Laudos SBK

## Estrutura da pasta

```
projeto_laudos/
  sistema_laudos_v2.html   ← interface do sistema
  servidor.py              ← servidor e API
  importar_excel.py        ← importa o Excel para o banco
  banco_laudos.db          ← banco de dados (criado automaticamente)
  README.md
```

---

## Instalação (uma única vez)

Você precisa ter o Python 3.8 ou superior instalado.

```bash
pip install openpyxl pandas
```

---

## Primeiro uso

### 1. Importe o Excel para o banco

```bash
python importar_excel.py data.xlsx
```

Isso cria o arquivo `banco_laudos.db` com todos os processos.
Pode rodar novamente sempre que chegar um Excel novo — processos com
status já alterado pelo analista (aguardando, concluído) não são sobrescritos.

### 2. Inicie o servidor

```bash
python servidor.py
```

### 3. Acesse no navegador

```
http://localhost:8000
```

Login padrão: `teste` / `1234`

---

## Uso diário

Sempre que for trabalhar no sistema:

```bash
python servidor.py
```

E acesse `http://localhost:8000`. O servidor pode ficar aberto o dia todo.
Para encerrar: `Ctrl+C` no terminal.

---

## Adicionar usuários

Para gerar o hash de um novo usuário:

```bash
python servidor.py --adduser joao senha123 "João Silva"
```

Copie a linha gerada e adicione no dict `USUARIOS` dentro do `servidor.py`.

---

## Fluxo dos processos

```
Excel importado
      │
      ▼
 Em andamento ──── analista preenche o laudo
      │
      │  falta documento?
      ▼
 Aguardando demanda ──── documento chegou? ──► Em andamento
      │
      │  laudo finalizado?  (futuro)
      ▼
  Concluído

 Sem contrato ──── apenas relatório (a implementar)
```

---

## O que fica salvo no banco

| Tabela      | O que armazena                                    |
|-------------|---------------------------------------------------|
| processos   | dados do processo + campos preenchidos no laudo   |
| contratos   | contratos vinculados a cada processo              |
| historico   | cada movimentação de status com data e usuário    |

---

## Backup

Basta copiar o arquivo `banco_laudos.db`. Ele contém tudo.
