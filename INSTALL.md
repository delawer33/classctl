# Установка classctl

## Linux

**1. Установите pipx** (если ещё не установлен):

```bash
sudo apt install pipx
pipx ensurepath
```

Откройте новый терминал (или выполните `source ~/.bashrc`).

**2. Установите classctl:**

```bash
pipx install git+https://github.com/delawer33/classctl@v0.1.1
```

**3. Выдайте права на ARP-сканирование** (один раз после установки):

```bash
sudo setcap cap_net_raw+ep "$(find ~/.local/share/pipx/venvs/classctl -name python3 -type f | head -1)"
```

**4. Запустите:**

```bash
classctl
```

Откройте браузер: http://127.0.0.1:8000

> **Важно:** при обновлении Python (`apt upgrade`) или самого classctl (`pipx upgrade classctl`) шаг 3 нужно повторить — обновление пересоздаёт виртуальное окружение и сбрасывает права.

---

## Windows

**1. Установите [Npcap](https://npcap.com/#download).**

При установке отметьте:
- «Install Npcap in WinPcap API-compatible Mode»
- «Allow non-admin users to capture packets» (если нужно запускать без прав администратора; иначе запускайте classctl от имени администратора)

**2. Установите pipx:**

```powershell
pip install pipx
pipx ensurepath
```

Перезапустите терминал.

**3. Установите classctl:**

```powershell
pipx install git+https://github.com/delawer33/classctl@v0.1.1
```

**4. Запустите** (в обычном или администраторском терминале, в зависимости от настроек Npcap):

```powershell
classctl
```

Откройте браузер: http://127.0.0.1:8000

---

## Обновление

```bash
pipx install git+https://github.com/delawer33/classctl@v0.2.0 --force
# Linux: после обновления повторите шаг 3 (setcap)
```
