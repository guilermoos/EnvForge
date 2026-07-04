# -*- coding: utf-8 -*-
import os
import time
import shutil
import subprocess
from envforge.config import MOUNTS
from envforge.manager import EnvManager
from envforge.logger import log

def mount_chroot(env_path):
    """Monta os 6 sistemas de arquivos necessários no chroot."""
    log.info(f"Iniciando montagem de sistemas de arquivos em {env_path}")
    for m_type, src, rel_path in MOUNTS:
        target = os.path.join(env_path, rel_path)
        os.makedirs(target, exist_ok=True)
        if EnvManager.is_path_mounted(target):
            log.debug(f"Sistema de arquivos {target} já está montado. Ignorando.")
            continue
            
        if m_type == "bind":
            cmd = ["mount", "--bind", src, target]
        else:
            cmd = ["mount", "-t", m_type, src, target]
        log.debug(f"Executando comando de montagem: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
    log.info("Montagens concluídas com sucesso.")

def kill_chroot_processes(env_path):
    """Encontra e finaliza todos os processos executando no chroot."""
    real_env_path = os.path.realpath(env_path)
    log.info(f"Escaneando processos ativos no chroot: {real_env_path}")
    pids_to_kill = []
    
    for pid_name in os.listdir("/proc"):
        if not pid_name.isdigit():
            continue
        pid = int(pid_name)
        try:
            root_link = os.readlink(f"/proc/{pid}/root")
            if os.path.realpath(f"/proc/{pid}/root") == real_env_path:
                pids_to_kill.append(pid)
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
            
    if not pids_to_kill:
        log.info("Nenhum processo interno encontrado no chroot.")
        return
        
    log.info(f"Encontrados {len(pids_to_kill)} processos rodando no chroot. Enviando SIGTERM (15)...")
    for pid in pids_to_kill:
        try:
            with open(f"/proc/{pid}/cmdline", "r") as f:
                cmdline = f.read().replace('\x00', ' ')
            log.debug(f"Matando PID {pid}: {cmdline}")
            os.kill(pid, 15)  # SIGTERM
        except (ProcessLookupError, FileNotFoundError):
            pass
        except Exception as e:
            log.warning(f"Não foi possível ler/matar PID {pid}: {e}")
            
    start_time = time.time()
    while time.time() - start_time < 2.0:
        still_running = []
        for pid in pids_to_kill:
            if os.path.exists(f"/proc/{pid}"):
                still_running.append(pid)
        if not still_running:
            log.info("Todos os processos do chroot foram finalizados com SIGTERM.")
            break
        time.sleep(0.1)
    else:
        still_running = [p for p in pids_to_kill if os.path.exists(f"/proc/{p}")]
        if still_running:
            log.warning(f"Processos remanescentes pós SIGTERM: {still_running}. Enviando SIGKILL (9)...")
            for pid in still_running:
                try:
                    os.kill(pid, 9)  # SIGKILL
                except ProcessLookupError:
                    pass

def unmount_chroot(env_path):
    """Desmonta os sistemas de arquivos em ordem reversa."""
    log.info(f"Iniciando desmontagem do chroot {env_path}")
    kill_chroot_processes(env_path)
    
    for _, _, rel_path in reversed(MOUNTS):
        target = os.path.join(env_path, rel_path)
        if EnvManager.is_path_mounted(target):
            log.debug(f"Desmontando: {target}")
            cmd = ["umount", target]
            res = subprocess.run(cmd, capture_output=True)
            if res.returncode != 0:
                log.debug(f"umount normal falhou para {target}. Executando umount preguiçoso (-l).")
                subprocess.run(["umount", "-l", target])
    log.info("Desmontagem concluída.")

def is_sshd_running(env_path):
    """Verifica se o daemon SSH do chroot está em execução."""
    real_env_path = os.path.realpath(env_path)
    for pid_name in os.listdir("/proc"):
        if not pid_name.isdigit():
            continue
        pid = int(pid_name)
        try:
            if os.path.realpath(f"/proc/{pid}/root") == real_env_path:
                with open(f"/proc/{pid}/cmdline", "r") as f:
                    cmdline = f.read()
                    if "/usr/sbin/sshd" in cmdline or "sshd" in cmdline:
                        return True
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return False

def load_packages_from_file():
    """
    Lê a lista de pacotes a partir de packages.txt.
    Ignora linhas vazias e comentários.
    Lança ValueError se o arquivo estiver ausente ou vazio.
    """
    from envforge.config import PACKAGES_CONFIG_PATH
    log.info(f"Carregando lista de pacotes de: {PACKAGES_CONFIG_PATH}")
    
    if not os.path.exists(PACKAGES_CONFIG_PATH):
        log.error(f"Arquivo de configuração de pacotes não existe: {PACKAGES_CONFIG_PATH}")
        raise FileNotFoundError(f"Arquivo de configuração de pacotes ausente: {PACKAGES_CONFIG_PATH}")
        
    packages = []
    with open(PACKAGES_CONFIG_PATH, "r") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            packages.append(stripped)
            
    if not packages:
        log.error(f"Nenhum pacote encontrado em: {PACKAGES_CONFIG_PATH}")
        raise ValueError(f"O arquivo de configuração de pacotes está vazio: {PACKAGES_CONFIG_PATH}")
        
    log.info(f"Pacotes carregados com sucesso: {packages}")
    return packages

def configure_apt_sources(env_path, repo_url):
    """
    Configura o arquivo /etc/apt/sources.list.d/ubuntu.sources no chroot.
    """
    log.info(f"Configurando APT sources no chroot {env_path} com espelho: {repo_url}")
    codename = "noble"
    os_release_path = os.path.join(env_path, "etc/os-release")
    if os.path.exists(os_release_path):
        with open(os_release_path, "r") as f:
            for line in f:
                if line.startswith("VERSION_CODENAME="):
                    codename = line.split("=")[1].strip().strip('"').strip("'")
                    break
    log.debug(f"Codinome do SO detectado no chroot: {codename}")
                    
    sources_dir = os.path.join(env_path, "etc/apt/sources.list.d")
    os.makedirs(sources_dir, exist_ok=True)
    
    main_sources_file = os.path.join(env_path, "etc/apt/sources.list")
    if os.path.exists(main_sources_file):
        with open(main_sources_file, "w") as f:
            f.write("# Gerenciado pelo EnvForge - Configurações movidas para sources.list.d/ubuntu.sources\n")
            
    ubuntu_sources_path = os.path.join(sources_dir, "ubuntu.sources")
    sources_content = f"""Types: deb
URIs: {repo_url}
Suites: {codename} {codename}-updates {codename}-backports
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: http://security.ubuntu.com/ubuntu
Suites: {codename}-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
"""
    with open(ubuntu_sources_path, "w") as f:
        f.write(sources_content)

def configure_and_install_ssh(env_path, ssh_port, ssh_pub_key, password):
    """
    Lê a lista de pacotes do arquivo packages.txt, instala todos de forma genérica
    no chroot e, caso o openssh-server esteja instalado, executa sua configuração.
    """
    log.info(f"Iniciando configure_and_install_ssh no chroot {env_path}")
    # 1. Carrega pacotes desacoplados
    packages = load_packages_from_file()
    log.debug(f"Pacotes a serem instalados: {packages}")
    
    # 2. Previne inicialização automática de daemons durante a instalação
    policy_path = os.path.join(env_path, "usr/sbin/policy-rc.d")
    os.makedirs(os.path.dirname(policy_path), exist_ok=True)
    with open(policy_path, "w") as f:
        f.write("#!/bin/sh\nexit 101\n")
    os.chmod(policy_path, 0o755)
    log.debug(f"Criada política temporária em: {policy_path}")
    
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    
    try:
        log.info("Executando apt-get update no chroot...")
        print(f"[Backend] Atualizando repositórios APT...")
        subprocess.run(["chroot", env_path, "apt-get", "update"], env=env, check=True)
        log.info("apt-get update concluído com sucesso.")
        
        log.info(f"Executando apt-get install no chroot para: {packages}")
        print(f"[Backend] Instalando pacotes: {', '.join(packages)}...")
        cmd = ["chroot", env_path, "apt-get", "install", "-y"] + packages
        res = subprocess.run(cmd, env=env)
        if res.returncode != 0:
            log.error(f"Erro na instalação dos pacotes. Código de retorno do apt-get: {res.returncode}")
            raise RuntimeError(f"Falha ao instalar pacotes. Verifique se todos os nomes no packages.txt são válidos: {packages}")
        log.info("Instalação dos pacotes concluída com sucesso.")
    except Exception as e:
        log.error(f"Exceção capturada na instalação/atualização do APT: {e}")
        raise
    finally:
        if os.path.exists(policy_path):
            try:
                os.remove(policy_path)
                log.debug(f"Removida política temporária {policy_path}")
            except Exception as e:
                log.warning(f"Erro ao remover política temporária {policy_path}: {e}")
                
    # 3. Executa pós-configuração do SSH se o openssh-server tiver sido instalado
    sshd_config_path = os.path.join(env_path, "etc/ssh/sshd_config")
    if os.path.exists(sshd_config_path):
        name = os.path.basename(env_path)
        log.info(f"Configurando hostname 'envforge' e hosts no chroot...")
        print("[Backend] Configurando hostname e rede local...")
        
        # Gravação de hostname
        with open(os.path.join(env_path, "etc/hostname"), "w") as f:
            f.write("envforge\n")
            
        # Gravação de debian_chroot para o prompt do bash
        with open(os.path.join(env_path, "etc/debian_chroot"), "w") as f:
            f.write("envforge\n")
            
        # Wrapper mock para o comando hostname (evita retornar o hostname do host)
        for host_path in ["bin/hostname", "usr/bin/hostname"]:
            h_bin = os.path.join(env_path, host_path)
            if os.path.exists(h_bin) or os.path.islink(h_bin):
                try:
                    os.remove(h_bin)
                except Exception as e:
                    log.warning(f"Erro ao remover {host_path} original: {e}")
            os.makedirs(os.path.dirname(h_bin), exist_ok=True)
            with open(h_bin, "w") as f:
                f.write("#!/bin/sh\necho envforge\n")
            os.chmod(h_bin, 0o755)
            
        # Gravação de hosts
        with open(os.path.join(env_path, "etc/hosts"), "w") as f:
            f.write("127.0.0.1\tlocalhost envforge\n::1\t\tlocalhost ip6-localhost ip6-loopback\nff02::1\t\tip6-allnodes\nff02::2\t\tip6-allrouters\n")
            

            
        # Criação do usuário nomeado de acordo com o ambiente
        user_exists = False
        try:
            res = subprocess.run(["chroot", env_path, "id", "-u", name], capture_output=True)
            if res.returncode == 0:
                user_exists = True
        except Exception:
            pass
            
        if not user_exists:
            log.info(f"Criando usuário de desenvolvimento '{name}' no chroot...")
            print(f"[Backend] Criando usuário de desenvolvimento '{name}'...")
            subprocess.run(["chroot", env_path, "useradd", "-m", "-s", "/bin/bash", "-U", name], check=True)
            subprocess.run(["chroot", env_path, "usermod", "-aG", "sudo", name], check=True)
            
            # Definir senha do usuário de forma personalizada
            p = subprocess.Popen(["chroot", env_path, "chpasswd"], stdin=subprocess.PIPE, text=True)
            p.communicate(input=f"{name}:{password}\n")
            
        # Configurar chaves SSH para o novo usuário
        log.info(f"Configurando chaves SSH autorizadas para o usuário '{name}'...")
        user_ssh_dir = os.path.join(env_path, f"home/{name}/.ssh")
        os.makedirs(user_ssh_dir, exist_ok=True)
        
        auth_keys_path = os.path.join(user_ssh_dir, "authorized_keys")
        with open(auth_keys_path, "w") as f:
            f.write(ssh_pub_key.strip() + "\n")
            
        # Ajusta permissões dentro do chroot de forma portável
        subprocess.run(["chroot", env_path, "chown", "-R", f"{name}:{name}", f"/home/{name}/.ssh"], check=True)
        subprocess.run(["chroot", env_path, "chmod", "700", f"/home/{name}/.ssh"], check=True)
        subprocess.run(["chroot", env_path, "chmod", "600", f"/home/{name}/.ssh/authorized_keys"], check=True)
        
        log.info("Configurando sshd_config com restrição de root...")
        print("[Backend] Configurando servidor SSH...")
        # Geração de chaves de host
        subprocess.run(["chroot", env_path, "ssh-keygen", "-A"], check=True)
        
        # Leitura e modificação do sshd_config
        config_lines = []
        with open(sshd_config_path, "r") as f:
            keys_to_override = ["Port", "PermitRootLogin", "PubkeyAuthentication", "AuthorizedKeysFile", "PasswordAuthentication", "UsePAM"]
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    config_lines.append(line)
                    continue
                parts = stripped.split()
                if parts and parts[0] in keys_to_override:
                    continue
                config_lines.append(line)
                
        config_lines.append("\n# EnvForge SSH Configurations\n")
        config_lines.append(f"Port {ssh_port}\n")
        config_lines.append("PermitRootLogin no\n")  # Desabilita login SSH direto como root
        config_lines.append("PubkeyAuthentication yes\n")
        config_lines.append("AuthorizedKeysFile .ssh/authorized_keys\n")
        config_lines.append("PasswordAuthentication yes\n")
        config_lines.append("UsePAM yes\n")
        
        with open(sshd_config_path, "w") as f:
            f.writelines(config_lines)
            
        # Desbloqueio e definição de senha padrão do root para 'root' (apenas para su - root local)
        log.debug("Definindo senha padrão do root como 'root'...")
        p = subprocess.Popen(["chroot", env_path, "chpasswd"], stdin=subprocess.PIPE, text=True)
        p.communicate(input="root:root\n")
        # Sobrescreve a variável de ambiente HOSTNAME e o prompt nos bashrcs do chroot
        for rc_file in ["etc/bash.bashrc", f"home/{name}/.bashrc", "root/.bashrc"]:
            rc_path = os.path.join(env_path, rc_file)
            if os.path.exists(rc_path):
                with open(rc_path, "a") as f:
                    f.write("\n# EnvForge Hostname overrides\n")
                    f.write("export HOSTNAME=envforge\n")
                    f.write("PS1='${debian_chroot:+($debian_chroot)}\\u@envforge:\\w\\$ '\n")
                    
        log.info("Pós-configuração do SSH e usuário concluída com sucesso.")

def start_sshd(env_path, ssh_port):
    """Inicia o daemon SSH no chroot."""
    run_sshd_path = os.path.join(env_path, "run/sshd")
    os.makedirs(run_sshd_path, exist_ok=True)
    os.chmod(run_sshd_path, 0o755)
    
    cmd = ["chroot", env_path, "/usr/sbin/sshd", "-p", str(ssh_port)]
    subprocess.run(cmd, check=True)
