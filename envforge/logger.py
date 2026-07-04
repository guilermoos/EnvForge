# -*- coding: utf-8 -*-
import os
import logging
import sys

def setup_logger():
    """
    Configura o sistema de logging para escrever em envforge.log.
    Se falhar por permissão, escreve em /tmp/envforge.log.
    """
    log_name = "envforge.log"
    log_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    log_path = os.path.join(log_dir, log_name)
    
    # Tenta abrir o arquivo para testar permissão de escrita
    try:
        with open(log_path, "a") as f:
            pass
    except PermissionError:
        log_path = os.path.join("/tmp", log_name)
        
    logger = logging.getLogger("EnvForge")
    logger.setLevel(logging.DEBUG)
    
    # Evita duplicar handlers
    if not logger.handlers:
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        try:
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except Exception:
            pass
            
    return logger

log = setup_logger()
