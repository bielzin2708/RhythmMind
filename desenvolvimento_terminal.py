"""Terminal de desenvolvimento com dados ficticios descartaveis, sem autenticar perfis."""

from api.desenvolvimento import dados_ficticios_temporarios
from main import main as executar_terminal


def main():
    with dados_ficticios_temporarios():
        print("Terminal ficticio e temporario. Nao acessa contas nem autentica perfis.")
        try:
            executar_terminal()
        except (KeyboardInterrupt, EOFError):
            print("\nTerminal encerrado; os dados ficticios temporarios serao descartados.")


if __name__ == "__main__":
    main()
