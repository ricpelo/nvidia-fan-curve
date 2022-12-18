import subprocess
import sys
import time

T_MIN: int = 50
T_MAX: int = 90
V_MIN: int = 0
V_MAX: int = 90
V_CEBADO: int = 30
SLEEP = 7

# Temperatura: velocidad
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


def get_temp(gpu: int) -> int:
    comando = ['nvidia-settings', f'-q=[gpu:{gpu}]/GPUCoreTemp', '-t']
    res = subprocess.run(comando, encoding='utf-8', check=True, stdout=subprocess.PIPE)
    return int(res.stdout.strip())


def get_speed(fan: int) -> int:
    comando = ['nvidia-settings', f'-q=[fan:{fan}]/GPUCurrentFanSpeed', '-t']
    res = subprocess.run(comando, encoding='utf-8', check=True, stdout=subprocess.PIPE)
    return int(res.stdout.strip())


def set_speed(fan: int, veloc: int) -> None:
    comando = ['nvidia-settings', f'-a=[fan:{fan}]/GPUTargetFanSpeed={veloc}', '-t']
    res = subprocess.run(comando, encoding='utf-8', check=True, stdout=subprocess.PIPE)


def set_speeds(veloc):
    for fan in range(get_num_fans()):
        set_speed(fan, veloc)


def set_fan_control(gpu: int, estado: int):
    comando = ['nvidia-settings', f'-a=[gpu:{gpu}]/GPUFanControlState={estado}', '-t']
    res = subprocess.run(comando, encoding='utf-8', check=True, stdout=subprocess.PIPE)


def set_fans_control(estado: int):
    for gpu in range(get_num_gpus()):
        set_fan_control(gpu, estado)


def get_num_gpus() -> int:
    comando = ['nvidia-settings', '-q=gpus', '-t']
    res = subprocess.run(comando, encoding='utf-8', check=True, stdout=subprocess.PIPE)
    return int(res.stdout.split('\n', 1)[0].split(' ', 1)[0])


def get_num_fans() -> int:
    comando = ['nvidia-settings', '-q=fans', '-t']
    res = subprocess.run(comando, encoding='utf-8', check=True, stdout=subprocess.PIPE)
    return int(res.stdout.split('\n', 1)[0].split(' ', 1)[0])


def log(s: str) -> None:
    print(s)


def cebador(fan, objetivo):
    if get_speed(fan) == 0 and objetivo > 0 and objetivo != V_CEBADO:
        log('Iniciando proceso de cebado...')
        set_speed(fan, V_CEBADO)
        while get_speed(fan) < V_CEBADO:
            log('Finalizando proceso de cebado...')
            time.sleep(SLEEP)


def get_temps() -> list[int]:
    return [get_temp(gpu) for gpu in range(get_num_gpus())]

def final() -> None:
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

        time.sleep(SLEEP)

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

print(25, buscar_objetivo(25, CURVA))
print(47, buscar_objetivo(47, CURVA))
print(52, buscar_objetivo(52, CURVA))
print(55, buscar_objetivo(55, CURVA))
print(61, buscar_objetivo(61, CURVA))
print(82, buscar_objetivo(82, CURVA))
print(88, buscar_objetivo(88, CURVA))

print(get_temp(0))

print(CURVA)
