import subprocess
import sys
import time
import psutil
import signal
import os


T_MIN: int = 50
T_MAX: int = 90
V_MIN: int = 0
V_MAX: int = 90
V_CEBADO: int = 30
SLEEP: int = 7

# Temperatura (ºC): velocidad (%)
CURVA: dict[int, int] = {
    # 50: 30,
    55: 45,
    60: 60,
    65: 64,
    70: 68,
    75: 75,
    80: 80,
    85: 85
}


def kill_already_running() -> None:
    salir = False
    while not salir:
        salir = True
        for p in psutil.process_iter():
            if os.getpid() == p.pid:
                continue
            cmdline = ' '.join(p.cmdline())
            if sys.argv[0] in cmdline:
                salir = False
                os.kill(p.pid, signal.SIGUSR1)
                log(f'Killed process {p.pid}')
                esperar()


def buscar_objetivo(temp: int, curva: dict[int, int]) -> tuple[int, int]:
    if temp < T_MIN:
        return (0, 0)
    for t, f in curva.items():
        if temp < t:
            return (t, f)
    return (T_MAX, V_MAX)


def siguiente_velocidad(actual: int, objetivo: int, curva: dict[int, int]) -> int:
    if actual == objetivo:
        return actual

    if objetivo == 0:
        return 0

    if actual < objetivo:
        for v in curva.values():
            if v <= actual:
                continue
            if v <= objetivo:
                return v
        return V_MAX

    for v in reversed(curva.values()):
        if v >= actual:
            continue
        if v >= objetivo:
            return v
    return V_MIN


def run_command(command: str) -> subprocess.CompletedProcess[str]:
    comando = ['nvidia-settings', command, '-t']
    return subprocess.run(comando, encoding='utf-8', check=True, stdout=subprocess.PIPE)


def get_query_num(query: str) -> int:
    return int(run_command(query).stdout.split('\n', 1)[0].split(' ', 1)[0])


def get_query_str(query: str) -> int:
    return int(run_command(query).stdout.strip())


def get_temp(gpu: int) -> int:
    return get_query_str(f'-q=[gpu:{gpu}]/GPUCoreTemp')


def get_temps() -> list[int]:
    return [get_temp(gpu) for gpu in range(get_num_gpus())]


def get_speed(fan: int) -> int:
    return get_query_str(f'-q=[fan:{fan}]/GPUCurrentFanSpeed')


def set_speed(fan: int, veloc: int) -> None:
    run_command(f'-a=[fan:{fan}]/GPUTargetFanSpeed={veloc}')


def set_speeds(veloc: int) -> None:
    for fan in range(get_num_fans()):
        set_speed(fan, veloc)


def set_fan_control(gpu: int, estado: int) -> None:
    run_command(f'-a=[gpu:{gpu}]/GPUFanControlState={estado}')


def set_fans_control(estado: int):
    for gpu in range(get_num_gpus()):
        set_fan_control(gpu, estado)


def get_num_gpus() -> int:
    return get_query_num('-q=gpus')


def get_num_fans() -> int:
    return get_query_num('-q=fans')


def log(s: str) -> None:
    print(s)


def esperar(tiempo=SLEEP):
    time.sleep(tiempo)


def cebador(fan: int, sgte_veloc: int) -> None:
    if get_speed(fan) == 0 and sgte_veloc > 0 and sgte_veloc != V_CEBADO:
        log('Iniciando proceso de cebado...')
        set_speed(fan, V_CEBADO)
        while get_speed(fan) < V_CEBADO:
            log('Finalizando proceso de cebado...')
            esperar()


def finalizar(_signum, _stack) -> None:
    i = 0

    while True:
        # Si todas las GPUs están por debajo de los 46º, nos salimos:
        if all(temp <= 46 for temp in get_temps()):
            break

        log('Esperando a que baje la temperatura...')

        # Al principio:
        if i == 0:
            mas_alta = next(iter(CURVA))
            for fan in range(get_num_fans()):
                # Si ya gira a más de 45%, probamos con 45%; si no, probamos con 30%:
                veloc = mas_alta if get_speed(fan) < mas_alta else V_CEBADO
                set_speed(fan, veloc)

        esperar()

        # Si después de 10 intentos, la temperatura sigue alta:
        if i == 10:
            # Probamos con todos al 60%:
            it = iter(CURVA)
            veloc = next(it)
            veloc = next(it)
            set_speeds(veloc)
            i += 1
        elif i < 10:
            i += 1

    set_fans_control(0)
    log('Fan control set back to auto mode.')
    sys.exit(0)


def finalizar_usr(_signum, _stack):
    msg = 'Proceso temp.py detenido'
    comando = ['notify-send', '-u', 'critical', msg]
    subprocess.run(comando, encoding='utf-8', check=True, stdout=subprocess.PIPE)
    log(msg)
    sys.exit(0)


def bucle(fan: int, curva: dict[int, int]) -> None:
    cur_temp = get_temp(fan)
    cur_speed = get_speed(fan)
    t, obj = buscar_objetivo(cur_temp, curva)
    sgte_veloc = siguiente_velocidad(cur_speed, obj, curva)
    if cur_speed != sgte_veloc:
        cebador(fan, sgte_veloc)
        set_speed(fan, sgte_veloc)

def main():
    sigs = {
        signal.SIGINT,
        signal.SIGHUP,
        signal.SIGQUIT,
        signal.SIGABRT,
        signal.SIGALRM,
        signal.SIGTERM
    }

    for sig in sigs:
        signal.signal(sig, finalizar)

    signal.signal(signal.SIGUSR1, finalizar_usr)
    kill_already_running()
    set_fans_control(1)
    log(f'Started process por {get_num_gpus()} GPUs and {get_num_fans()} fans')

    while True:
        for fan in range(get_num_fans()):
            bucle(fan, CURVA)
            esperar()
