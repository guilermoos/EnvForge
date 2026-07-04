# -*- coding: utf-8 -*-
import os
import sys
import re
import time
import fcntl
import curses
import subprocess
from envforge.config import SSH_PORT, BANNER, UBUNTU_DEFAULT_MIRROR
from envforge.manager import EnvManager
from envforge.logger import log

# ==============================================================================
# PROMPTS E DIÁLOGOS INTERATIVOS DO CURSES
# ==============================================================================
def check_and_obtain_sudo():
    """
    Verifica se o sudo possui credenciais ativas. Caso contrário, desativa o curses,
    solicita a senha no terminal padrão e depois reestabelece a janela do curses.
    """
    log.debug("Verificando credenciais sudo...")
    res = subprocess.run(["sudo", "-n", "true"], capture_output=True)
    if res.returncode == 0:
        log.debug("Credenciais sudo ativas.")
        return True
        
    log.info("Sudo inativo. Desativando curses para capturar senha no terminal...")
    curses.endwin()
    print("\n[EnvForge] Este programa precisa rodar operações como administrador.")
    print("[EnvForge] Por favor, insira a senha do sudo abaixo:")
    try:
        res = subprocess.run(["sudo", "true"])
        success = (res.returncode == 0)
    except Exception as e:
        log.error(f"Erro ao obter permissão de sudo: {e}")
        success = False
        
    # Re-inicializa o curses
    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    
    if success:
        log.info("Sudo autenticado com sucesso. Curses reestabelecido.")
    else:
        log.warning("Falha na autenticação do sudo.")
    return success

def run_background_action(args_list, stdscr, title):
    """
    Executa comandos do backend sob sudo com animação de progresso (spinner)
    e exibição da última linha do stdout/stderr em tempo real para evitar deadlocks.
    """
    log.info(f"Executando ação em segundo plano: {title} - argumentos: {args_list}")
    if not check_and_obtain_sudo():
        log.error("Sudo negado pelo usuário. Abortando ação.")
        show_error_dialog(stdscr, "Permissão de administrador (sudo) negada.")
        return False
        
    root_script = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "envforge.py")
    cmd = ["sudo", sys.executable, root_script] + args_list
    
    log.debug(f"Iniciando subprocesso: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    
    # Configura os pipes como não-bloqueantes
    for pipe in [proc.stdout, proc.stderr]:
        if pipe:
            fd = pipe.fileno()
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinner_idx = 0
    stdscr.nodelay(True)
    last_line = "Iniciando operação..."
    
    try:
        while proc.poll() is None:
            # 1. Consome e limpa a saída do stdout
            try:
                out = proc.stdout.readline()
                if out:
                    last_line = out.strip()
                    log.debug(f"[Subprocess stdout]: {last_line}")
            except IOError:
                pass
                
            # 2. Consome e limpa a saída do stderr para prevenir deadlocks
            try:
                err = proc.stderr.readline()
                if err:
                    err_line = err.strip()
                    last_line = f"ERR: {err_line}"
                    log.debug(f"[Subprocess stderr]: {err_line}")
            except IOError:
                pass
                
            h, w = stdscr.getmaxyx()
            stdscr.erase()
            
            box_h, box_w = 7, min(w - 4, 70)
            start_y = max(0, (h - box_h) // 2)
            start_x = max(0, (w - box_w) // 2)
            
            for y in range(start_y, start_y + box_h):
                for x in range(start_x, start_x + box_w):
                    if y == start_y or y == start_y + box_h - 1:
                        stdscr.addch(y, x, curses.ACS_HLINE)
                    elif x == start_x or x == start_x + box_w - 1:
                        stdscr.addch(y, x, curses.ACS_VLINE)
            stdscr.addch(start_y, start_x, curses.ACS_ULCORNER)
            stdscr.addch(start_y, start_x + box_w - 1, curses.ACS_URCORNER)
            stdscr.addch(start_y + box_h - 1, start_x, curses.ACS_LLCORNER)
            stdscr.addch(start_y + box_h - 1, start_x + box_w - 1, curses.ACS_LRCORNER)
            
            stdscr.addstr(start_y + 1, start_x + 2, f" {title} ", curses.A_BOLD)
            
            spin_char = spinner[spinner_idx]
            spinner_idx = (spinner_idx + 1) % len(spinner)
            
            stdscr.addstr(start_y + 3, start_x + 4, f"[{spin_char}] {last_line[:box_w - 10]}")
            stdscr.addstr(start_y + 5, start_x + 4, "Aguarde a finalização das tarefas do sistema...", curses.A_DIM)
            
            stdscr.refresh()
            time.sleep(0.1)
    finally:
        stdscr.nodelay(False)
        
    stdout_all, stderr_all = proc.communicate()
    # Log das saídas finais acumuladas
    if stdout_all:
        for l in stdout_all.splitlines():
            log.debug(f"[Subprocess stdout final]: {l}")
    if stderr_all:
        for l in stderr_all.splitlines():
            log.debug(f"[Subprocess stderr final]: {l}")
            
    log.info(f"Subprocesso finalizado com código de retorno: {proc.returncode}")
    if proc.returncode == 0:
        return True
    else:
        err_msg = stderr_all.strip() or last_line or "Erro desconhecido durante execução."
        log.error(f"Erro na execução da tarefa {title}: {err_msg}")
        show_error_dialog(stdscr, f"Falha na execução:\n{err_msg}")
        return False

def show_error_dialog(stdscr, message):
    h, w = stdscr.getmaxyx()
    lines = message.split("\n")
    box_h = len(lines) + 4
    box_w = max(len(l) for l in lines) + 6
    box_w = min(max(box_w, 40), w - 4)
    
    start_y = max(0, (h - box_h) // 2)
    start_x = max(0, (w - box_w) // 2)
    
    win = curses.newwin(box_h, box_w, start_y, start_x)
    win.box()
    win.keypad(True)
    
    color_pair = 0
    if curses.has_colors():
        curses.init_pair(10, curses.COLOR_RED, -1)
        color_pair = curses.color_pair(10)
        
    win.addstr(1, 2, " ERRO ", curses.A_BOLD | color_pair)
    
    for i, line in enumerate(lines):
        win.addstr(2 + i, 3, line[:box_w - 6])
        
    win.addstr(box_h - 2, (box_w - 28) // 2, "[ Pressione qualquer tecla ]", curses.A_REVERSE)
    win.refresh()
    win.getch()

def show_info_dialog(stdscr, title, message):
    h, w = stdscr.getmaxyx()
    lines = message.split("\n")
    box_h = min(h - 4, len(lines) + 4)
    box_w = min(w - 6, max(len(l) for l in lines) + 6)
    box_w = max(box_w, 50)
    
    start_y = max(0, (h - box_h) // 2)
    start_x = max(0, (w - box_w) // 2)
    
    win = curses.newwin(box_h, box_w, start_y, start_x)
    win.box()
    win.keypad(True)
    
    color_pair = 0
    if curses.has_colors():
        curses.init_pair(11, curses.COLOR_CYAN, -1)
        color_pair = curses.color_pair(11)
        
    win.addstr(1, 2, f" {title} ", curses.A_BOLD | color_pair)
    
    for i in range(box_h - 4):
        if i < len(lines):
            win.addstr(2 + i, 3, lines[i][:box_w - 6])
            
    win.addstr(box_h - 2, (box_w - 28) // 2, "[ Pressione qualquer tecla ]", curses.A_REVERSE)
    win.refresh()
    win.getch()

def show_confirm_dialog(stdscr, title, message):
    h, w = stdscr.getmaxyx()
    lines = message.split("\n")
    box_h = len(lines) + 5
    box_w = max(len(l) for l in lines) + 6
    box_w = min(max(box_w, 40), w - 4)
    
    start_y = max(0, (h - box_h) // 2)
    start_x = max(0, (w - box_w) // 2)
    
    win = curses.newwin(box_h, box_w, start_y, start_x)
    win.box()
    win.keypad(True)
    
    win.addstr(1, 2, f" {title} ", curses.A_BOLD)
    for i, line in enumerate(lines):
        win.addstr(2 + i, 3, line[:box_w - 6])
        
    win.addstr(box_h - 2, (box_w - 20) // 2, "[S] Sim   [N] Não", curses.A_BOLD)
    win.refresh()
    
    while True:
        ch = win.getch()
        if ch in [ord('S'), ord('s'), ord('Y'), ord('y')]:
            return True
        elif ch in [ord('N'), ord('n'), 27]:
            return False

def show_input_dialog(stdscr, title, prompt):
    h, w = stdscr.getmaxyx()
    box_h = 7
    box_w = min(50, w - 4)
    
    start_y = max(0, (h - box_h) // 2)
    start_x = max(0, (w - box_w) // 2)
    
    win = curses.newwin(box_h, box_w, start_y, start_x)
    win.box()
    win.keypad(True)
    
    win.addstr(1, 2, f" {title} ", curses.A_BOLD)
    win.addstr(3, 3, prompt[:box_w - 6])
    
    curses.curs_set(1)
    curses.echo()
    
    input_win = curses.newwin(1, box_w - 6, start_y + 4, start_x + 3)
    input_win.keypad(True)
    
    win.refresh()
    input_win.refresh()
    
    user_input = ""
    try:
        user_input = input_win.getstr().decode('utf-8').strip()
    except Exception:
        pass
        
    curses.noecho()
    curses.curs_set(0)
    
    return user_input

def show_input_dialog_with_default(stdscr, title, prompt, default_value=""):
    h, w = stdscr.getmaxyx()
    box_h = 8
    box_w = min(70, w - 4)
    
    start_y = max(0, (h - box_h) // 2)
    start_x = max(0, (w - box_w) // 2)
    
    win = curses.newwin(box_h, box_w, start_y, start_x)
    win.box()
    win.keypad(True)
    
    win.addstr(1, 2, f" {title} ", curses.A_BOLD)
    win.addstr(3, 3, prompt[:box_w - 6])
    win.addstr(4, 3, "Deixe em branco para o mirror padrão do Ubuntu.", curses.A_DIM)
    
    curses.curs_set(1)
    
    input_str = list(default_value)
    cursor_pos = len(input_str)
    
    input_y = 5
    input_x = 3
    input_w = box_w - 6
    
    while True:
        win.addstr(input_y, input_x, "_" * input_w, curses.A_DIM)
        display_str = "".join(input_str)[:input_w]
        win.addstr(input_y, input_x, display_str)
        win.move(input_y, input_x + min(cursor_pos, input_w - 1))
        win.refresh()
        
        ch = win.getch()
        if ch in [10, 13]: # ENTER
            break
        elif ch == 27: # ESC
            input_str = []
            break
        elif ch in [8, 127, curses.KEY_BACKSPACE]: # BACKSPACE
            if cursor_pos > 0:
                input_str.pop(cursor_pos - 1)
                cursor_pos -= 1
        elif ch == curses.KEY_LEFT:
            cursor_pos = max(0, cursor_pos - 1)
        elif ch == curses.KEY_RIGHT:
            cursor_pos = min(len(input_str), cursor_pos + 1)
        elif ch in [curses.KEY_HOME, 1]: # Ctrl+A ou HOME
            cursor_pos = 0
        elif ch in [curses.KEY_END, 5]: # Ctrl+E ou END
            cursor_pos = len(input_str)
        elif 32 <= ch <= 126: # Caracteres normais imprimíveis
            if len(input_str) < input_w - 2:
                input_str.insert(cursor_pos, chr(ch))
                cursor_pos += 1
                
    curses.curs_set(0)
    return "".join(input_str).strip()

def init_colors():
    if curses.has_colors():
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)     # Bordas e cabeçalhos
        curses.init_pair(2, curses.COLOR_GREEN, -1)    # Status Executando
        curses.init_pair(3, curses.COLOR_YELLOW, -1)   # Status Parado
        curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE) # Linha Selecionada
        curses.init_pair(5, curses.COLOR_MAGENTA, -1)  # Logo Banner
        curses.init_pair(6, curses.COLOR_WHITE, -1)    # Texto Geral
        curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_CYAN) # Rodapé


# ==============================================================================
# CLASSE PRINCIPAL TUIAPP
# ==============================================================================
class TUIApp:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.envs = []
        self.selected_idx = 0
        
    def run(self):
        curses.curs_set(0)
        init_colors()
        self.refresh_envs()
        
        while True:
            self.draw()
            ch = self.stdscr.getch()
            
            if ch == curses.KEY_UP:
                if self.envs:
                    self.selected_idx = max(0, self.selected_idx - 1)
            elif ch == curses.KEY_DOWN:
                if self.envs:
                    self.selected_idx = min(len(self.envs) - 1, self.selected_idx + 1)
            elif ch in [ord('C'), ord('c')]:
                self.create_env()
            elif ch in [ord('S'), ord('s')]:
                self.start_env()
            elif ch in [ord('P'), ord('p')]:
                self.stop_env()
            elif ch in [ord('R'), ord('r')]:
                self.remove_env()
            elif ch in [ord('I'), ord('i')]:
                self.show_env_info()
            elif ch in [ord('U'), ord('u')]:
                self.refresh_envs()
            elif ch == curses.KEY_RESIZE:
                self.stdscr.clear()
            elif ch in [ord('Q'), ord('q')]:
                if show_confirm_dialog(self.stdscr, "Sair", "Deseja realmente fechar o EnvForge?"):
                    break
                    
    def refresh_envs(self):
        self.envs = EnvManager.get_environments()
        if self.selected_idx >= len(self.envs):
            self.selected_idx = max(0, len(self.envs) - 1)
            
    def draw(self):
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()
        
        start_y = 1
        if w >= 80 and h >= 28:
            for i, line in enumerate(BANNER):
                x = max(0, (w - len(line)) // 2)
                self.stdscr.addstr(start_y + i, x, line, curses.color_pair(5) | curses.A_BOLD)
            start_y += len(BANNER) + 1
        else:
            title = "--- EnvForge: Gerenciador de Ambientes chroot ---"
            self.stdscr.addstr(start_y, max(0, (w - len(title)) // 2), title, curses.color_pair(1) | curses.A_BOLD)
            start_y += 2
            
        col1_w = max(15, int(w * 0.25))
        col2_w = 15
        col3_w = 12
        col4_w = max(20, w - col1_w - col2_w - col3_w - 8)
        
        header_fmt = f"%-{col1_w}s   %-{col2_w}s   %-{col3_w}s   %-{col4_w}s"
        header_str = header_fmt % ("Nome do Ambiente", "Estado", "Porta SSH", "Data de Criação")
        
        table_start_y = start_y
        self.stdscr.addstr(table_start_y, 2, "┌" + "─" * (w - 6) + "┐", curses.color_pair(1))
        self.stdscr.addstr(table_start_y + 1, 2, "│ " + header_str[:w-8] + " │", curses.color_pair(1) | curses.A_BOLD)
        self.stdscr.addstr(table_start_y + 2, 2, "├" + "─" * (w - 6) + "┤", curses.color_pair(1))
        
        table_h = min(10, max(3, h - table_start_y - 12))
        
        for idx in range(table_h):
            row_y = table_start_y + 3 + idx
            if idx < len(self.envs):
                env = self.envs[idx]
                row_str = header_fmt % (
                    env["name"],
                    env["status"],
                    str(env["ssh_port"]),
                    env["created_at"]
                )
                
                if idx == self.selected_idx:
                    style = curses.color_pair(4) | curses.A_BOLD
                    self.stdscr.addstr(row_y, 2, "│", curses.color_pair(1))
                    padded_row = " " + row_str[:w-8]
                    padded_row += " " * ((w - 6) - len(padded_row))
                    self.stdscr.addstr(row_y, 3, padded_row, style)
                    self.stdscr.addstr(row_y, w - 4, "│", curses.color_pair(1))
                else:
                    self.stdscr.addstr(row_y, 2, "│ ", curses.color_pair(1))
                    status_pair = curses.color_pair(2) if env["status"] == "Em Execução" else curses.color_pair(3)
                    
                    part1 = f"%-{col1_w}s   " % env["name"]
                    self.stdscr.addstr(row_y, 4, part1)
                    
                    status_str = f"%-{col2_w}s" % env["status"]
                    self.stdscr.addstr(row_y, 4 + len(part1), status_str, status_pair | curses.A_BOLD)
                    
                    part2_fmt = "   %-" + str(col3_w) + "s   %-" + str(col4_w) + "s"
                    part2_str = part2_fmt % (str(env["ssh_port"]), env["created_at"])
                    self.stdscr.addstr(row_y, 4 + len(part1) + len(status_str), part2_str[:w-8 - (len(part1)+len(status_str))])
                    
                    self.stdscr.addstr(row_y, w - 4, " │", curses.color_pair(1))
            else:
                self.stdscr.addstr(row_y, 2, "│", curses.color_pair(1))
                if not self.envs and idx == table_h // 2:
                    msg = "Nenhum ambiente cadastrado. Pressione [C] para criar."
                    x = max(3, (w - len(msg)) // 2)
                    self.stdscr.addstr(row_y, x, msg, curses.A_DIM)
                else:
                    self.stdscr.addstr(row_y, 3, " " * (w - 8))
                self.stdscr.addstr(row_y, w - 4, "│", curses.color_pair(1))
                
        self.stdscr.addstr(table_start_y + 3 + table_h, 2, "└" + "─" * (w - 6) + "┘", curses.color_pair(1))
        
        info_y = table_start_y + 4 + table_h
        info_h = max(4, h - info_y - 2)
        
        self.stdscr.addstr(info_y, 2, " Detalhes do Ambiente Selecionado ", curses.color_pair(1) | curses.A_BOLD)
        
        if self.envs and self.selected_idx < len(self.envs):
            env = self.envs[self.selected_idx]
            details = [
                f"Diretório:  /opt/envforge/{env['name']}",
                f"Status:     {env['status']}",
                f"Servidor:   SSH na porta {env['ssh_port']} (Host: 127.0.0.1)",
                f"Comando:    ssh -p {env['ssh_port']} root@127.0.0.1",
                f"VS Code:    Use a extensão Remote - SSH e conecte ao host '{env['name']}'"
            ]
            for idx, detail in enumerate(details):
                if idx < info_h - 1:
                    self.stdscr.addstr(info_y + 1 + idx, 4, detail[:w-8])
        else:
            self.stdscr.addstr(info_y + 2, 4, "Selecione um ambiente acima para visualizar informações.", curses.A_DIM)
            
        footer_y = h - 1
        footer_str = " [C] Criar   [S] Iniciar   [P] Parar   [R] Remover   [I] Info   [U] Atualizar   [Q] Sair "
        padded_footer = footer_str + " " * (w - len(footer_str))
        try:
            self.stdscr.addstr(footer_y, 0, padded_footer[:w], curses.color_pair(7) | curses.A_BOLD)
        except curses.error:
            pass
        
        self.stdscr.refresh()

    def create_env(self):
        name = show_input_dialog(self.stdscr, "Criar Ambiente", "Digite o nome do novo ambiente chroot:")
        if not name:
            return
            
        if not bool(re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*$", name)):
            show_error_dialog(self.stdscr, "Nome inválido!\nUse apenas letras, números e traços.\nO nome deve começar com letra ou número.")
            return
            
        if any(e["name"] == name for e in self.envs):
            show_error_dialog(self.stdscr, f"O ambiente '{name}' já existe.")
            return
            
        # 1. Carregar repositório padrão salvo nas configurações
        saved_repo = EnvManager.get_default_repo_url()
        
        # 2. Solicitar repositório ao usuário
        repo_url = show_input_dialog_with_default(
            self.stdscr,
            "Repositório APT",
            "Digite a URL do repositório/mirror do APT:",
            saved_repo
        )
        
        if repo_url == "":
            repo_url = UBUNTU_DEFAULT_MIRROR
            
        # 3. Perguntar sobre senha personalizada
        deseja_senha = show_confirm_dialog(
            self.stdscr,
            "Senha do Usuário",
            f"Deseja escolher uma senha personalizada para o usuário '{name}'?\n\n"
            f"[S] Sim (digitar uma senha)\n"
            f"[N] Usar padrão (nome do ambiente: '{name}')"
        )
        
        password = name
        if deseja_senha:
            password = show_input_dialog(
                self.stdscr,
                "Senha Personalizada",
                f"Digite a senha para o novo usuário '{name}':"
            )
            if not password:
                password = name
            
        port = SSH_PORT
        
        try:
            pub_key, priv_key_path = EnvManager.get_user_ssh_key()
        except Exception as e:
            show_error_dialog(self.stdscr, f"Falha ao obter/gerar chave SSH:\n{e}")
            return
            
        success = run_background_action(
            ["--backend-create", name, str(port), pub_key, repo_url, password],
            self.stdscr,
            f"Criando ambiente '{name}'"
        )
        
        if success:
            # 3. Persistir a URL utilizada com sucesso nas configurações
            EnvManager.save_default_repo_url(repo_url)
            
            try:
                EnvManager.update_ssh_config(name, port, priv_key_path)
            except Exception as e:
                show_error_dialog(self.stdscr, f"Ambiente criado, mas falhou ao atualizar ~/.ssh/config:\n{e}")
            self.refresh_envs()
            show_info_dialog(
                self.stdscr,
                "Sucesso",
                f"Ambiente '{name}' criado com sucesso!\n"
                f"Porta SSH configurada: {port}\n"
                f"Repositório APT: {repo_url}\n\n"
                f"A entrada foi inserida em seu ~/.ssh/config.\n"
                f"Você pode se conectar no VS Code usando:\n"
                f"Remote-SSH -> Conectar ao Host -> {name}"
            )

    def start_env(self):
        if not self.envs:
            return
        env = self.envs[self.selected_idx]
        if env["status"] == "Em Execução":
            show_info_dialog(self.stdscr, "Aviso", f"O ambiente '{env['name']}' já está ativo.")
            return
            
        # Verifica se há outro ambiente rodando
        running_env = EnvManager.get_running_environment()
        if running_env:
            msg = f"O ambiente '{running_env}' já está em execução.\n" \
                  f"Deseja pará-lo para poder iniciar '{env['name']}'?"
            if not show_confirm_dialog(self.stdscr, "Trocar de Ambiente", msg):
                return
                
            stop_success = run_background_action(
                ["--backend-stop", running_env],
                self.stdscr,
                f"Parando ambiente '{running_env}'"
            )
            if not stop_success:
                show_error_dialog(self.stdscr, f"Falha ao parar o ambiente '{running_env}'.")
                self.refresh_envs()
                return
            
        success = run_background_action(
            ["--backend-start", env["name"]],
            self.stdscr,
            f"Iniciando ambiente '{env['name']}'"
        )
        if success:
            try:
                _, priv_key_path = EnvManager.get_user_ssh_key()
                EnvManager.update_ssh_config(env["name"], env["ssh_port"], priv_key_path)
            except Exception as e:
                log.warning(f"Erro ao atualizar ~/.ssh/config ao iniciar: {e}")
            self.refresh_envs()

    def stop_env(self):
        if not self.envs:
            return
        env = self.envs[self.selected_idx]
        if env["status"] == "Parado":
            show_info_dialog(self.stdscr, "Aviso", f"O ambiente '{env['name']}' já está parado.")
            return
            
        if not show_confirm_dialog(self.stdscr, "Parar Ambiente", f"Deseja parar o ambiente '{env['name']}'?"):
            return
            
        success = run_background_action(
            ["--backend-stop", env["name"]],
            self.stdscr,
            f"Parando ambiente '{env['name']}'"
        )
        if success:
            self.refresh_envs()

    def remove_env(self):
        if not self.envs:
            return
        env = self.envs[self.selected_idx]
        
        if not show_confirm_dialog(
            self.stdscr,
            "Remover Ambiente",
            f"Deseja realmente remover '{env['name']}'?\nEsta ação EXCLUIRÁ PERMANENTEMENTE todos os arquivos!"
        ):
            return
            
        success = run_background_action(
            ["--backend-remove", env["name"]],
            self.stdscr,
            f"Removendo ambiente '{env['name']}'"
        )
        if success:
            try:
                EnvManager.remove_ssh_config(env["name"])
            except Exception as e:
                show_error_dialog(self.stdscr, f"Arquivos removidos, mas falhou ao limpar ~/.ssh/config:\n{e}")
            self.refresh_envs()
            show_info_dialog(self.stdscr, "Sucesso", f"Ambiente '{env['name']}' foi excluído.")

    def show_env_info(self):
        if not self.envs:
            return
        env = self.envs[self.selected_idx]
        
        msg = f"Nome:                {env['name']}\n"
        msg += f"Status:              {env['status']}\n"
        msg += f"Porta SSH:           {env['ssh_port']}\n"
        msg += f"Criação:             {env['created_at']}\n"
        msg += f"Caminho no Host:     /opt/envforge/{env['name']}\n\n"
        msg += "--- Conexão ---\n"
        msg += f"Terminal: ssh {env['name']}\n"
        msg += f"Alternativo: ssh -p {env['ssh_port']} root@127.0.0.1\n\n"
        msg += "--- Integração VS Code ---\n"
        msg += "1. Certifique-se de ter a extensão 'Remote - SSH' instalada.\n"
        msg += "2. Clique em Conectar ao Host no VS Code e escolha:\n"
        msg += f"   {env['name']}\n"
        msg += "3. Tudo pronto! O VS Code iniciará o editor direto no chroot."
        
        show_info_dialog(self.stdscr, f"Metadados: {env['name']}", msg)
