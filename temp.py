#!/usr/bin/python3

import subprocess
import sys
import time
import signal
import os
import datetime
import psutil


T_MIN: int = 50   # Temperatura por debajo de la cual el ventilador se apaga
T_MAX: int = 90   # Temperatura a partir de la cual se enciende al 100%
T_FIN: int = 45   # Temperatura a alcanzar al salir
V_MIN: int = 0    # Velocidad mínima del ventilador
V_MAX: int = 90   # Velocidad máxima del ventilador
V_CEB: int = 30   # Velocidad de cebado
SLEEP: int = 7    # Segundos de espera entre comprobaciones


# Curva de temperaturas y velocidades
# Temperatura (ºC): velocidad (%)
CURVA: dict[int, int] = {
    55: 45,
    60: 60,
    65: 64,
    70: 68,
    75: 75,
    80: 80,
    85: 85
}


# Ventilador: curva
CURVAS: dict[int, dict[int, int]] = {
    0: CURVA,
    # 1: CURVA
}


# GPU: [Lista de ventiladores]
GPUS_FANS: dict[int, list[int]] = {
    0: [0],
    # 1: [1],
}


class Fan:
    __num_fans: int = -1


    def __init__(self, f_num: int, params: dict[str, int], curva: dict[int, int]) -> None:
        self.__f_num = f_num
        self.__curva = curva
        self.__v_min = params['v_min']
        self.__v_max = params['v_max']
        self.__v_ceb = params['v_ceb']


    @classmethod
    def get_num_fans(cls) -> int:
        if cls.__num_fans < 0:
            cls.__num_fans = get_query_num('-q=fans')
        return cls.__num_fans


    def get_f_num(self) -> int:
        return self.__f_num


    def get_v_min(self):
        return self.__v_min


    def get_v_max(self):
        return self.__v_max


    def get_v_ceb(self):
        return self.__v_ceb


    def get_curva(self):
        return self.__curva


    def cebador(self, sgte_veloc: int) -> bool:
        if self.get_speed() == 0 and sgte_veloc > 0 and sgte_veloc > self.get_v_ceb():
            log('Iniciando proceso de cebado...')
            self.set_speed(self.get_v_ceb())
            while self.get_speed() < self.get_v_ceb():
                log('Finalizando proceso de cebado...')
                esperar()
            return True
        return False


    def get_speed(self) -> int:
        return get_query_str(f'-q=[fan:{self.get_f_num()}]/GPUCurrentFanSpeed')


    def set_speed(self, veloc: int) -> None:
        log(run_command(f'-a=[fan:{self.get_f_num()}]/GPUTargetFanSpeed={veloc}')
            .stdout.strip())


    def siguiente_velocidad(self, actual: int, objetivo: int) -> int:
        if actual == objetivo:
            return actual
        if objetivo == 0:
            return 0
        if actual < objetivo:
            for v in self.__curva.values():
                if v <= actual:
                    continue
                if v <= objetivo:
                    return v
            return self.get_v_max()
        for v in reversed(self.__curva.values()):
            if v >= actual:
                continue
            if v >= objetivo:
                return v
        return self.get_v_min()


class GPU:
    __num_gpus: int = -1


    def __init__(self, g_num: int, params: dict[str, int], fans: list[Fan]) -> None:
        self.__g_num = g_num
        self.__fans = fans
        self.__t_min = params['t_min']
        self.__t_max = params['t_max']
        self.__t_fin = params['t_fin']


    @classmethod
    def get_num_gpus(cls) -> int:
        if cls.__num_gpus < 0:
            cls.__num_gpus = get_query_num('-q=gpus')
        return cls.__num_gpus


    def g_num(self) -> int:
        return self.__g_num


    def get_temp(self) -> int:
        return get_query_str(f'-q=[gpu:{self.g_num()}]/GPUCoreTemp')


    def get_fans(self) -> list[Fan]:
        return self.__fans


    def get_t_min(self):
        return self.__t_min


    def get_t_max(self):
        return self.__t_max


    def get_t_fin(self):
        return self.__t_fin


    def set_fan_control(self, estado: int) -> None:
        log(run_command(f'-a=[gpu:{self.g_num()}]/GPUFanControlState={estado}')
            .stdout.strip())


    def buscar_objetivo(self, temp: int, fan: Fan) -> tuple[int, int]:
        if temp < self.get_t_min():
            return (0, 0)
        for t, f in fan.get_curva().items():
            if temp < t:
                return (t, f)
        return (self.get_t_max(), fan.get_v_max())


class Manager:
    def __init__(self):
        self.__gpus = []


    def get_gpus(self) -> list[GPU]:
        return self.__gpus


    def set_gpus(self, gpus: list[GPU]) -> None:
        self.__gpus = gpus


    def get_temps(self) -> list[int]:
        return [gpu.get_temp() for gpu in self.get_gpus()]


    def set_speeds(self, veloc: int) -> None:
        for gpu in self.get_gpus():
            for fan in gpu.get_fans():
                fan.set_speed(veloc)


    def set_fans_control(self, estado: int):
        for gpu in self.get_gpus():
            gpu.set_fan_control(estado)


    def bucle(self, temp_actual: int, gpu: GPU, fan: Fan) -> None:
        veloc_actual = fan.get_speed()
        _, objetivo = gpu.buscar_objetivo(temp_actual, fan)
        sgte_veloc = fan.siguiente_velocidad(veloc_actual, objetivo)
        if veloc_actual != 0 and sgte_veloc == 0 and temp_actual > gpu.get_t_fin():
            log(f'No se apaga el ventilador por encima de {gpu.get_t_fin()} grados.')
            return
        if veloc_actual != sgte_veloc:
            log(f'Cambiando a velocidad {sgte_veloc}, con objetivo {objetivo}.')
            if not fan.cebador(sgte_veloc):
                fan.set_speed(sgte_veloc)


def get_query_num(query: str) -> int:
    return int(run_command(query).stdout.split('\n', 1)[0].split(' ', 1)[0])


def get_query_str(query: str) -> int:
    return int(run_command(query).stdout.strip())


def run_command(command: str) -> subprocess.CompletedProcess[str]:
    comando = ['nvidia-settings', command, '-t']
    return subprocess.run(
        comando,
        encoding='utf-8',
        check=True,
        stdout=subprocess.PIPE
    )


def kill_already_running() -> None:
    salir = False
    while not salir:
        salir = True
        for p in psutil.process_iter():
            if os.getpid() == p.pid:
                continue
            file = os.path.basename(__file__)
            cmdline = ' '.join(p.cmdline())
            if file in cmdline:
                salir = False
                os.kill(p.pid, signal.SIGUSR1)
                log(f'Killed process {p.pid}')
                esperar()


def hay_mas_procesos() -> bool:
    for p in psutil.process_iter():
        if os.getpid() == p.pid:
            continue
        file = os.path.basename(__file__)
        cmdline = ' '.join(p.cmdline())
        if file in cmdline:
            return True
    return False


def log(s: str) -> None:
    ts = datetime.datetime.now().replace(microsecond=0)
    print(f'{ts} - {s}')
    sys.stdout.flush()


def esperar(tiempo=SLEEP):
    time.sleep(tiempo)


def finalizar(_signum, _frame) -> None:
    veloc = 0
    i = 0

    while True:
        # Si todas las GPUs están por debajo de T_FIN, nos salimos:
        try:
            if all(gpu.get_temp() <= gpu.get_t_fin() for gpu in manager.get_gpus()):
                break
        except ValueError:
            break

        log('Esperando a que baje la temperatura...')

        # Al principio:
        if i == 0:
            for gpu in manager.get_gpus():
                for fan in gpu.get_fans():
                    # Si gira a menos de la primera velocidad de la curva,
                    # probamos primero con V_CEB. Si no, probamos a la
                    # primera velocidad:
                    it = iter(fan.get_curva())
                    v_primera = next(it)
                    veloc = fan.get_v_ceb() if fan.get_speed() < v_primera else v_primera
                    fan.set_speed(veloc)

        esperar()

        # Si después de 10 intentos, la temperatura sigue alta:
        if i == 10:
            # Subimos la velocidad:
            for gpu in manager.get_gpus():
                for fan in gpu.get_fans():
                    it = iter(fan.get_curva())
                    v_primera = next(it)
                    veloc = v_primera if fan.get_speed() < v_primera else next(it)
                    fan.set_speed(veloc)
            i += 1
        elif i < 10:
            i += 1

    manager.set_fans_control(0)
    log('Fan control set back to auto mode.')
    sys.exit(0)


def finalizar_usr(_signum, _frame):
    msg = 'Proceso temp.py detenido'
    comando = ['notify-send', '-u', 'critical', msg]
    subprocess.run(comando, encoding='utf-8', check=True, stdout=subprocess.PIPE)
    log(msg)
    sys.exit(0)


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

    # kill_already_running()
    if hay_mas_procesos():
        log('Hay otro proceso ejecutándose.')
        sys.exit(1)

    try:
        log(f'Started process por {GPU.get_num_gpus()} GPUs and {Fan.get_num_fans()} fans.')
    except ValueError:
        log('No se pudo obtener el número de GPUs y ventiladores.')
        sys.exit(1)

    gpus = []

    for g_num, f_nums in GPUS_FANS.items():
        fans = []
        for f_num in f_nums:
            fan = Fan(f_num, {'v_min': V_MIN, 'v_max': V_MAX, 'v_ceb': V_CEB}, CURVA)
            fans.append(fan)
        gpu = GPU(g_num, {'t_min': T_MIN, 't_max': T_MAX, 't_fin': T_FIN}, fans)

    manager.set_gpus(gpus)


    manager.set_fans_control(1)
    manager.set_speeds(0)

    while True:
        for gpu in manager.get_gpus():
            temp_actual = gpu.get_temp()
            for fan in gpu.get_fans():
                manager.bucle(temp_actual, gpu, fan)
            esperar()


manager: Manager = Manager()

if __name__ == '__main__':
    main()
