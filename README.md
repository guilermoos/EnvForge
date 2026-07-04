# EnvForge

<p align="center">
  <img src="icon_app.png" alt="EnvForge Logo" width="150">
</p>

<p align="center">
  <b>Gerenciador autônomo de ambientes de desenvolvimento chroot isolados e integrados ao VS Code.</b>
</p>

## 📋 Descrição do Projeto

O **EnvForge** é uma ferramenta de linha de comando e interface gráfica de terminal (TUI) projetada para provisionar, gerenciar e isolar ambientes de desenvolvimento Linux de forma leve e portável. Utilizando a tecnologia de conteinerização nativa `chroot` combinada com imagens de sistema de arquivos altamente comprimidas em `SquashFS`, o EnvForge permite criar sandboxes completas baseadas no Ubuntu em poucos segundos, fornecendo isolamento de processos e bibliotecas sem a necessidade de hipervisores (máquinas virtuais) ou daemons de segundo plano (como o Docker).

O grande diferencial do projeto é o provisionamento automático de acesso SSH seguro para usuários comuns e a integração transparente com o recurso de desenvolvimento remoto (*Remote - SSH*) do editor VS Code, otimizando o fluxo de trabalho de engenharia de software diretamente do host.

## 🎯 Público-Alvo e Casos de Uso

O EnvForge foi desenvolvido para atender aos seguintes cenários de desenvolvimento e administração de sistemas:

* **Isolamento de Projetos e Dependências**: Desenvolvedores que precisam manter ambientes limpos no sistema host, evitando conflitos de versões de compiladores, runtimes (Python, Node.js, Go) e bancos de dados locais.
* **Ambientes de Teste de Implantação (DevOps)**: Engenheiros de infraestrutura que necessitam validar scripts de provisionamento e comportamento de aplicações em um sistema operacional limpo e idêntico ao de produção.
* **Otimização em Hardware Restrito**: Ambientes com limitações de hardware (memória RAM e processamento) onde a execução de máquinas virtuais completas ou múltiplos contêineres Docker geram overhead excessivo no sistema.

## 🚀 Principais Funcionalidades

* **Provisionamento Instantâneo**: Extração automatizada do sistema de arquivos comprimido (`rootfs.squashfs`) base em tempo recorde.
* **Criação de Usuário de Desenvolvimento**: Criação automatizada de um usuário comum nomeado com o mesmo nome do ambiente chroot, com shell padrão (`/bin/bash`), diretório `home` e permissões de administrador (`sudo`).
* **Segurança no Acesso SSH**: Restrição de acesso ao usuário `root` por conexões remotas (`PermitRootLogin no`), priorizando o login seguro do usuário criado para o ambiente.
* **Isolamento de Hostname**: Redefinição estática do hostname do ambiente para `envforge` no terminal do chroot, prevenindo vazamento visual do hostname do host físico.
* **Prevenção de Conflitos (Porta Fixa)**: Controle de concorrência que impede a execução simultânea de dois ambientes na mesma porta SSH (`2222`), encerrando montagens e processos ociosos de forma segura antes de iniciar o novo ambiente.
* **Decodificação de Dependências**: Declaração externa de pacotes a instalar na criação do chroot por meio do arquivo `envforge/packages.txt`.

---

## 📐 Decisões de Arquitetura e Engenharia

A arquitetura do EnvForge foi construída sob princípios de leveza, manutenibilidade e baixo acoplamento:

### 1. Conteinerização via Chroot e SquashFS
Ao contrário do Docker, que adiciona complexidade com pontes de rede virtual, camadas de drivers de armazenamento e daemons em background, o EnvForge utiliza a chamada de sistema `chroot` clássica do Linux. Os processos que rodam dentro do chroot são executados nativamente pelo kernel do host, resultando em:
* **Overhead de memória nulo**: O consumo de RAM é restrito apenas aos processos em execução.
* **Desempenho nativo de E/S (Input/Output)**: A escrita e leitura de disco ocorrem diretamente no sistema de arquivos do host.
* O template inicial do sistema é distribuído comprimido com o algoritmo **XZ (SquashFS)**, reduzindo o tamanho de distribuição do software pela metade e permitindo a extração instantânea sem dependência de rede.

### 2. Tratamento de Privilégios e Mapeamento de Contexto
A criação de pontos de montagem virtuais (`/proc`, `/sys`, `/dev`, `/dev/pts`) e o comando chroot exigem privilégios elevados de root (`sudo`). Executar o programa puramente como root faria com que chaves SSH e atalhos fossem gerados sob o diretório do administrador (`/root/.ssh/config`), inviabilizando o acesso ao usuário comum do sistema host.
**Solução**: O EnvForge analisa as variáveis de ambiente `SUDO_USER`, `SUDO_UID` e `SUDO_GID` no momento da inicialização para resgatar o contexto do usuário comum. As chaves de acesso do host e o arquivo de atalhos do SSH (`~/.ssh/config`) são gravados e têm sua propriedade (`chown`) atribuída de volta ao usuário real, assegurando que o VS Code rodando no host acesse a chave de identidade de forma nativa e sem avisos de segurança de permissões.

### 3. Mascaramento de Hostname e prompts do Shell
O chroot por padrão compartilha o namespace UTS do sistema host, fazendo com que o hostname real do seu computador seja exibido dentro do ambiente isolado. Para garantir isolamento visual e conformidade em scripts internos:
* O EnvForge substitui `/bin/hostname` e `/usr/bin/hostname` dentro do chroot por scripts wrappers que interceptam a chamada de sistema e retornam estaticamente a string `envforge`.
* O arquivo `/etc/debian_chroot` é configurado para adicionar a etiqueta `envforge` ao prompt de comandos.
* Os arquivos de inicialização do bash (`/etc/bash.bashrc`, `/home/{user}/.bashrc` e `/root/.bashrc`) são injetados com a redefinição da variável `PS1`, exibindo o prompt de forma padronizada no formato `usuario@envforge:~$`.

### 4. Interface de Usuário via Curses (TUI)
Para manter o gerenciador enxuto e livre de dependências de servidores gráficos locais (como Electron, Qt ou servidores HTTP locais), a interface visual foi desenvolvida utilizando a biblioteca padrão `curses`. O processamento de logs e triggers de pacotes complexos é feito em subprocessos assíncronos e não-bloqueantes de forma a prevenir deadlocks no buffer do sistema operacional.

---

## 🛠️ Tecnologias Utilizadas

* **Linguagem Principal**: Python 3
* **Interface**: Python Curses (TUI)
* **Estrutura de Imagem**: SquashFS (compressão XZ)
* **Virtualização/Isolamento**: Linux Chroot, Bind Mounts
* **Serviço de Comunicação**: OpenSSH Server / Client
* **Empacotamento**: Debian Packaging System (`dpkg-deb`)

---

## 📥 Instalação e Uso

### Instalação no Sistema (Recomendado)
Para instalar o EnvForge e todas as suas dependências em distribuições baseadas em Debian/Ubuntu, utilize o instalador `.deb` gerado na pasta do projeto:
```bash
sudo apt install ./envforge_1.0.0_amd64.deb
```
A instalação cria automaticamente:
* O atalho global `/usr/bin/envforge` no path do sistema.
* O lançador desktop `EnvForge` no menu de aplicativos do sistema.
* O mapeamento do ícone oficial para uso no launcher.

### Execução via Código Fonte (Desenvolvimento)
Certifique-se de que os pacotes de utilitários de sistema estejam instalados no seu host:
```bash
sudo apt install squashfs-tools python3-pil
```
Inicie a aplicação executando o arquivo principal:
```bash
python3 envforge.py
```
