# -*- coding: utf-8 -*-
import os
import sys
import json
import argparse
import shutil
import subprocess
import curses
from datetime import datetime

from envforge.config import BASE_DIR, SQUASHFS_PATH
from envforge.manager import EnvManager
from envforge.backend import mount_chroot, unmount_chroot, is_sshd_running, start_sshd, configure_and_install_ssh, configure_apt_sources
from envforge.tui import TUIApp
from envforge.logger import log

def run_cli():
    parser = argparse.ArgumentParser(description="EnvForge - Gerenciador de Ambientes chroot")
    
    # Comandos de backend
    parser.add_argument("--backend-create", nargs=5, metavar=("NAME", "PORT", "PUB_KEY", "REPO_URL", "PASSWORD"),
                        help="Cria o chroot extraindo o rootfs e instalando SSH")
    parser.add_argument("--backend-start", metavar="NAME",
                        help="Monta partições e inicia o daemon SSH do chroot")
    parser.add_argument("--backend-stop", metavar="NAME",
                        help="Finaliza os processos no chroot e desmonta partições")
    parser.add_argument("--backend-remove", metavar="NAME",
                        help="Desmonta partições e remove os diretórios do chroot")
    
    args = parser.parse_args()
    
    if args.backend_create:
        name, port, pub_key, repo_url, password = args.backend_create
        log.info(f"CLI: --backend-create iniciado para o ambiente '{name}' na porta {port}. Repositório: {repo_url}")
        try:
            env_path = os.path.join(BASE_DIR, name)
            log.debug(f"Garantindo diretório base do EnvForge {BASE_DIR}")
            print(f"[Backend] Criando diretório base {BASE_DIR}...")
            os.makedirs(BASE_DIR, exist_ok=True)
            os.chmod(BASE_DIR, 0o755)
            
            if os.path.exists(env_path):
                log.error(f"Erro: O diretório do ambiente {env_path} já existe.")
                print(f"Erro: O diretório do ambiente {env_path} já existe.", file=sys.stderr)
                sys.exit(1)
                
            log.info(f"Extraindo SquashFS {SQUASHFS_PATH} para {env_path}...")
            print(f"[Backend] Extraindo {SQUASHFS_PATH} para {env_path}...")
            subprocess.run(["unsquashfs", "-d", env_path, SQUASHFS_PATH], check=True)
            os.chmod(env_path, 0o755)
            
            log.debug(f"Configurando DNS resolv.conf...")
            print("[Backend] Configurando DNS resolv.conf...")
            resolv_dst = os.path.join(env_path, "etc/resolv.conf")
            os.makedirs(os.path.dirname(resolv_dst), exist_ok=True)
            if os.path.exists(resolv_dst) or os.path.islink(resolv_dst):
                try:
                    os.remove(resolv_dst)
                except Exception as e:
                    log.warning(f"Erro ao remover resolv.conf anterior: {e}")
            with open(resolv_dst, "w") as f:
                f.write("nameserver 8.8.8.8\nnameserver 1.1.1.1\nnameserver 8.8.4.4\n")
                
            log.debug(f"Configurando mirror APT: {repo_url}")
            print("[Backend] Configurando fontes do APT (sources.list.d)...")
            configure_apt_sources(env_path, repo_url)
                
            log.debug(f"Montando chroot...")
            print("[Backend] Montando sistemas de arquivos virtuais...")
            mount_chroot(env_path)
            
            try:
                log.debug("Chamando configure_and_install_ssh...")
                print("[Backend] Atualizando repositórios e instalando OpenSSH...")
                configure_and_install_ssh(env_path, port, pub_key, password)
            except Exception as e:
                log.error(f"Erro durante instalação/configuração dentro do chroot: {e}")
                raise
            finally:
                log.debug("Desmontando chroot pós-instalação...")
                print("[Backend] Desmontando sistemas de arquivos temporários...")
                unmount_chroot(env_path)
                
            log.debug("Salvando metadados chroot...")
            print("[Backend] Gravando arquivo de metadados...")
            metadata = {
                "name": name,
                "ssh_port": int(port),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            metadata_path = os.path.join(env_path, "envforge_metadata.json")
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=4)
            os.chmod(metadata_path, 0o644)
            
            log.info(f"Ambiente '{name}' criado com sucesso via CLI.")
            print(f"[Backend] Criação de '{name}' concluída com sucesso!")
            sys.exit(0)
        except Exception as e:
            log.error(f"Exceção capturada ao criar ambiente via CLI: {e}")
            print(f"Erro: {e}", file=sys.stderr)
            sys.exit(1)
            
    elif args.backend_start:
        name = args.backend_start
        log.info(f"CLI: --backend-start iniciado para '{name}'")
        try:
            env_path = os.path.join(BASE_DIR, name)
            if not os.path.exists(env_path):
                log.error(f"Erro: Ambiente '{name}' não existe.")
                print(f"Erro: Ambiente '{name}' não existe.", file=sys.stderr)
                sys.exit(1)
                
            running_env = EnvManager.get_running_environment()
            if running_env and running_env != name:
                log.error(f"Erro: O ambiente '{running_env}' já está em execução. Tentativa de iniciar '{name}' negada.")
                print(f"Erro: O ambiente '{running_env}' já está em execução. Pare-o antes de iniciar outro.", file=sys.stderr)
                sys.exit(1)
                
            metadata_path = os.path.join(env_path, "envforge_metadata.json")
            with open(metadata_path, "r") as f:
                meta = json.load(f)
            port = meta["ssh_port"]
            
            log.debug(f"Montando dependências para iniciar...")
            print(f"[Backend] Ativando montagens para '{name}'...")
            mount_chroot(env_path)
            
            if not is_sshd_running(env_path):
                log.info(f"Iniciando sshd no chroot na porta {port}...")
                print(f"[Backend] Iniciando OpenSSH na porta {port}...")
                start_sshd(env_path, port)
            else:
                log.info("sshd já está rodando neste chroot.")
                print(f"[Backend] OpenSSH já está em execução para '{name}'.")
                
            log.info(f"Ambiente '{name}' foi iniciado com sucesso.")
            print(f"[Backend] Ambiente '{name}' está ativo.")
            sys.exit(0)
        except Exception as e:
            log.error(f"Exceção capturada ao iniciar ambiente via CLI: {e}")
            print(f"Erro: {e}", file=sys.stderr)
            sys.exit(1)
            
    elif args.backend_stop:
        name = args.backend_stop
        log.info(f"CLI: --backend-stop iniciado para '{name}'")
        try:
            env_path = os.path.join(BASE_DIR, name)
            if not os.path.exists(env_path):
                log.error(f"Erro: Ambiente '{name}' não existe.")
                print(f"Erro: Ambiente '{name}' não existe.", file=sys.stderr)
                sys.exit(1)
                
            print(f"[Backend] Parando processos e desmontando '{name}'...")
            unmount_chroot(env_path)
            log.info(f"Ambiente '{name}' foi parado com sucesso.")
            print(f"[Backend] Ambiente '{name}' foi parado.")
            sys.exit(0)
        except Exception as e:
            log.error(f"Exceção capturada ao parar ambiente via CLI: {e}")
            print(f"Erro: {e}", file=sys.stderr)
            sys.exit(1)
            
    elif args.backend_remove:
        name = args.backend_remove
        log.info(f"CLI: --backend-remove iniciado para '{name}'")
        try:
            env_path = os.path.join(BASE_DIR, name)
            if not os.path.exists(env_path):
                log.error(f"Erro: Ambiente '{name}' não existe.")
                print(f"Erro: Ambiente '{name}' não existe.", file=sys.stderr)
                sys.exit(1)
                
            log.debug("Removendo entradas SSH config...")
            try:
                EnvManager.remove_ssh_config(name)
            except Exception as e:
                log.warning(f"Erro ao remover ssh config do host: {e}")
                
            print(f"[Backend] Desmontando dependências de '{name}'...")
            unmount_chroot(env_path)
            
            log.debug("Limpando arquivos no chroot base...")
            print(f"[Backend] Removendo arquivos de '{name}'...")
            shutil.rmtree(env_path)
            log.info(f"Ambiente '{name}' foi excluído com sucesso.")
            print(f"[Backend] Ambiente '{name}' foi excluído.")
            sys.exit(0)
        except Exception as e:
            log.error(f"Exceção capturada ao remover ambiente via CLI: {e}")
            print(f"Erro: {e}", file=sys.stderr)
            sys.exit(1)
            
    else:
        log.info("Iniciando TUI gráfica do EnvForge...")
        try:
            curses.wrapper(lambda stdscr: TUIApp(stdscr).run())
        except KeyboardInterrupt:
            log.info("Interface fechada por interrupção do teclado.")
            pass
        except Exception as e:
            log.critical(f"Erro fatal na execução da TUI: {e}")
            raise
        sys.exit(0)
