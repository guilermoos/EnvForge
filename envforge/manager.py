# -*- coding: utf-8 -*-
import os
import json
import socket
import subprocess
from envforge.config import BASE_DIR, SSH_PORT
from envforge.logger import log

def get_real_user_ssh_dir():
    """
    Retorna o diretório ~/.ssh do usuário real (mesmo se estiver rodando sob sudo).
    """
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            import pwd
            user_info = pwd.getpwnam(sudo_user)
            return os.path.join(user_info.pw_dir, ".ssh")
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), ".ssh")

def chown_to_real_user(path):
    """
    Se estiver rodando sob sudo, altera o proprietário do arquivo/diretório
    para o usuário original (SUDO_UID / SUDO_GID).
    """
    sudo_uid = os.environ.get("SUDO_UID")
    sudo_gid = os.environ.get("SUDO_GID")
    if sudo_uid and sudo_gid:
        try:
            os.chown(path, int(sudo_uid), int(sudo_gid))
        except Exception:
            pass

class EnvManager:
    @staticmethod
    def get_environments():
        """
        Retorna a lista de todos os ambientes configurados e seus status.
        Esta operação é executada como usuário comum lendo metadados públicos.
        """
        envs = []
        if not os.path.exists(BASE_DIR):
            return envs
            
        for name in os.listdir(BASE_DIR):
            env_path = os.path.join(BASE_DIR, name)
            if not os.path.isdir(env_path) or name.endswith("_tmp"):
                continue
            metadata_path = os.path.join(env_path, "envforge_metadata.json")
            if not os.path.exists(metadata_path):
                continue
                
            try:
                with open(metadata_path, "r") as f:
                    meta = json.load(f)
                
                # O status é determinado verificando se o /proc está montado no chroot
                proc_path = os.path.join(env_path, "proc")
                running = EnvManager.is_path_mounted(proc_path)
                
                envs.append({
                    "name": meta["name"],
                    "ssh_port": meta["ssh_port"],
                    "created_at": meta.get("created_at", "N/A"),
                    "status": "Em Execução" if running else "Parado"
                })
            except Exception:
                continue
                
        envs.sort(key=lambda x: x["name"])
        return envs

    @staticmethod
    def is_path_mounted(path):
        """Verifica se um caminho está montado no host."""
        real_path = os.path.realpath(path)
        try:
            with open("/proc/mounts", "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and os.path.realpath(parts[1]) == real_path:
                        return True
        except Exception:
            pass
        return False

    @staticmethod
    def get_running_environment():
        """
        Retorna o nome do ambiente atualmente em execução (com proc montado), ou None.
        """
        if not os.path.exists(BASE_DIR):
            return None
        for name in os.listdir(BASE_DIR):
            env_path = os.path.join(BASE_DIR, name)
            if not os.path.isdir(env_path) or name.endswith("_tmp"):
                continue
            proc_path = os.path.join(env_path, "proc")
            if EnvManager.is_path_mounted(proc_path):
                return name
        return None

    @staticmethod
    def get_user_ssh_key():
        """
        Busca uma chave pública SSH existente no ~/.ssh/ do usuário original.
        Se não existir nenhuma, gera um par de chaves próprio para o EnvForge.
        Retorna uma tupla (conteúdo_da_chave_pública, caminho_da_chave_privada).
        """
        ssh_dir = get_real_user_ssh_dir()
        os.makedirs(ssh_dir, exist_ok=True)
        chown_to_real_user(ssh_dir)
        
        candidates = ["id_ed25519.pub", "id_rsa.pub", "id_ecdsa.pub"]
        for cand in candidates:
            path = os.path.join(ssh_dir, cand)
            if os.path.exists(path):
                priv_path = os.path.join(ssh_dir, cand[:-4])
                with open(path, "r") as f:
                    return f.read().strip(), priv_path
                    
        envforge_pub = os.path.join(ssh_dir, "id_envforge.pub")
        envforge_priv = os.path.join(ssh_dir, "id_envforge")
        if os.path.exists(envforge_pub):
            with open(envforge_pub, "r") as f:
                return f.read().strip(), envforge_priv
                
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", envforge_priv],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        chown_to_real_user(envforge_priv)
        chown_to_real_user(envforge_pub)
        os.chmod(envforge_priv, 0o600)
        os.chmod(envforge_pub, 0o644)
        with open(envforge_pub, "r") as f:
            return f.read().strip(), envforge_priv

    @staticmethod
    def update_ssh_config(name, port, priv_key_path):
        """Adiciona ou atualiza a entrada do ambiente no arquivo ~/.ssh/config do usuário real."""
        ssh_dir = get_real_user_ssh_dir()
        os.makedirs(ssh_dir, exist_ok=True)
        chown_to_real_user(ssh_dir)
        config_path = os.path.join(ssh_dir, "config")
        
        content = ""
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                content = f.read()
                
        lines = content.splitlines()
        new_lines = []
        in_block = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("Host ") and len(stripped.split()) > 1 and stripped.split()[1] == name:
                in_block = True
                continue
            elif in_block and stripped.startswith("Host "):
                in_block = False
            if not in_block:
                new_lines.append(line)
                
        entry = f"""
Host {name}
    HostName 127.0.0.1
    Port {port}
    User {name}
    UserKnownHostsFile /dev/null
    StrictHostKeyChecking no
"""
        if priv_key_path:
            entry += f"    IdentityFile {priv_key_path}\n"
            
        new_content = "\n".join(new_lines).strip() + "\n" + entry
        with open(config_path, "w") as f:
            f.write(new_content)
        chown_to_real_user(config_path)
        os.chmod(config_path, 0o644)

    @staticmethod
    def remove_ssh_config(name):
        """Remove a entrada do ambiente do arquivo ~/.ssh/config do usuário real."""
        ssh_dir = get_real_user_ssh_dir()
        config_path = os.path.join(ssh_dir, "config")
        if not os.path.exists(config_path):
            return
            
        with open(config_path, "r") as f:
            content = f.read()
            
        lines = content.splitlines()
        new_lines = []
        in_block = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("Host ") and len(stripped.split()) > 1 and stripped.split()[1] == name:
                in_block = True
                continue
            elif in_block and stripped.startswith("Host "):
                in_block = False
            if not in_block:
                new_lines.append(line)
                
        new_content = "\n".join(new_lines).strip() + "\n"
        with open(config_path, "w") as f:
            f.write(new_content)
        chown_to_real_user(config_path)
        os.chmod(config_path, 0o644)

    @staticmethod
    def get_default_repo_url():
        """
        Retorna a URL do repositório padrão salva nas configurações.
        Se não existir, retorna uma string vazia.
        """
        config_dir = os.path.expanduser("~/.config/envforge")
        config_path = os.path.join(config_dir, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
                    return config.get("default_repo_url", "")
            except Exception:
                pass
        return ""

    @staticmethod
    def save_default_repo_url(url):
        """
        Salva a URL do repositório padrão nas configurações persistentes.
        """
        config_dir = os.path.expanduser("~/.config/envforge")
        config_path = os.path.join(config_dir, "config.json")
        try:
            os.makedirs(config_dir, exist_ok=True)
            config = {}
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r") as f:
                        config = json.load(f)
                except Exception:
                    pass
            config["default_repo_url"] = url
            with open(config_path, "w") as f:
                json.dump(config, f, indent=4)
        except Exception:
            pass
