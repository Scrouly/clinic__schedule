#!/usr/bin/env python3
import os
import customtkinter
import PyInstaller.__main__

# Автоматически находим путь к установленной библиотеке customtkinter
ctk_path = os.path.dirname(customtkinter.__file__)

# Формируем список аргументов для PyInstaller
args = [
    'gui_app.py',  # Главный файл запуска
    '--onedir',  # Сборка в виде ПАПКИ с зависимостями (вместо одного файла)
    '--noconsole',  # Отключить консоль при запуске приложения
    '--name=CityClinicSchedule',  # Имя папки и готового .exe файла

    # ИСПРАВЛЕНО: убрали дублирующуюся папку, так как ресурсы лежат в корне проекта
    '--icon=resources/icon.ico',

    # Пробрасываем внутренние данные customtkinter (темы, шрифты)
    f'--add-data={ctk_path}{os.pathsep}customtkinter',

    # ИСПРАВЛЕНО: копируем ресурсы напрямую из текущей корневой директории
    f'--add-data=resources{os.pathsep}resources',
]

print("[ИНФО] Начинаем компиляцию приложения в режиме директории...")
PyInstaller.__main__.run(args)
print("[УСПЕХ] Сборка завершена!")