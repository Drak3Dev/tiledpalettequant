# Tiled Palette Quantizer (Python)

Порт [tiledpalettequant](https://github.com/rilden/tiledpalettequant) с JavaScript на Python
с десктопным интерфейсом на tkinter. Работает полностью локально, без интернета, на Linux, macOS и Windows.

- **Оригинальный автор алгоритма и веб-версии:** [rilden](https://github.com/rilden)
- **Автор порта на Python:** Claude (ИИ-модель от [Anthropic](https://www.anthropic.com)),
  по заказу [Drak3Dev](https://github.com/Drak3Dev)

Программа квантует изображение так, как это нужно для ретро-консолей (NES, SNES, Game Boy Color, GBA,
Mega Drive и т.п.): картинка режется на тайлы, у каждого тайла своя палитра из небольшого набора
палитр, и в каждой палитре всего несколько цветов.

![пример](tiledpalettequant/carina-nebula.png)

## Быстрая установка одной командой

**Linux / macOS** (в терминале):

```bash
curl -fsSL https://raw.githubusercontent.com/Drak3Dev/tiledpalettequant/main/python/install.sh | bash
```

**Windows** (в PowerShell или в «Выполнить» Win+R):

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Drak3Dev/tiledpalettequant/main/python/install.ps1 | iex"
```

Скрипт скачивает программу, создаёт для неё отдельное виртуальное окружение Python, ставит зависимости
и создаёт ярлыки:

- **Linux:** пункт в меню приложений и команды `tiledpalettequant` и `tiledpalettequant-cli` в `~/.local/bin`.
- **macOS:** приложение в `~/Applications` и те же команды.
- **Windows:** ярлыки в меню «Пуск» и на рабочем столе. Если Python не установлен, скрипт поставит его через winget.

Повторный запуск той же команды обновляет программу.

### Удаление

**Linux / macOS:** команда `tiledpalettequant-uninstall` или

```bash
curl -fsSL https://raw.githubusercontent.com/Drak3Dev/tiledpalettequant/main/python/uninstall.sh | bash
```

**Windows:** «Параметры → Приложения → Tiled Palette Quantizer → Удалить» или

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Drak3Dev/tiledpalettequant/main/python/uninstall.ps1 | iex"
```

Удаляется всё, что поставил установщик: папка программы с её виртуальным окружением, ярлыки и команды.
Python и системные пакеты не трогаются.

На Linux tkinter иногда нужно поставить отдельно (см. таблицу ниже). Скрипт подскажет команду, если его нет.

## Ручная установка

Нужен Python 3.9+ с tkinter.

| Система | Как получить tkinter |
|---|---|
| Windows | установщик с python.org (галочка «tcl/tk and IDLE» включена по умолчанию) |
| macOS | установщик с python.org; для Homebrew: `brew install python-tk` |
| Debian / Ubuntu | `sudo apt install python3-tk` |
| Fedora | `sudo dnf install python3-tkinter` |
| Arch | `sudo pacman -S tk` |

Затем в папке проекта:

```bash
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

pip install -r requirements.txt
```

Интернет нужен только на время `pip install`. Чтобы поставить на машину вообще без сети, скачай колёса
заранее на машине с той же ОС и версией Python: `pip download -r requirements.txt -d wheels`, перенеси папку
`wheels` и выполни `pip install --no-index --find-links wheels -r requirements.txt`.

**numba** не обязательна, но без неё квантование примерно в 100 раз медленнее: на картинке 256×144
это 0.3 секунды против полуминуты и больше. При первом запуске numba компилирует код (5–20 секунд,
в статусной строке пишется «Подготовка...»), потом результат берётся из кэша.

**tkinterdnd2** тоже не обязательна: с ней картинку можно перетаскивать в окно мышкой.

## Запуск

```bash
python run.py                  # интерфейс
python run.py картинка.png     # интерфейс сразу с картинкой
python -m tiledpalettequant    # то же самое
```

На Windows можно запускать без консольного окна: `pythonw run.py`.

Можно установить как пакет (`pip install .[all]`), тогда появятся команды `tiledpalettequant` (интерфейс)
и `tiledpalettequant-cli` (командная строка).

Язык интерфейса выбирается по системной локали. Принудительно: переменная окружения `TPQ_LANG=ru`
или `TPQ_LANG=en`.

### Интерфейс

- Слева настройки (те же, что в веб-версии), кнопка «Квантовать» (Ctrl+Enter или F5) запускает расчёт,
  повторное нажатие останавливает его. Промежуточный результат показывается по ходу работы.
- Исходник и результат показываются рядом и прокручиваются синхронно. Колесо мыши — прокрутка,
  Shift+колесо — по горизонтали, Ctrl+колесо — масштаб, перетаскивание мышью — сдвиг.
- «Сохранить картинку» (Ctrl+S) — PNG или BMP. Если всего цветов не больше 256, PNG сохраняется
  индексированным (8 бит, палитра в файле, в прозрачных режимах индекс 0 каждой палитры прозрачный).
  Индекс пикселя = номер_палитры × цветов_в_палитре + номер_цвета.
- «Сохранить палитру» — PNG-полоска палитр, по строке на палитру.

### Командная строка

```bash
python -m tiledpalettequant cli input.png -o out.png --palettes 8 --colors 16 --bits 5 \
    --tile-width 8 --tile-height 8 --color-zero transparent --dither slow --seed 1
```

Все параметры: `python -m tiledpalettequant cli --help`. Рядом с картинкой сохраняется и палитра
(`out-palette.png`, отключается `--no-palette`).

### Из Python

```python
from tiledpalettequant import Options, ColorZero, Dither, load_image, quantize

result = quantize(load_image("in.png"), Options(num_palettes=4, colors_per_palette=16,
                                                color_zero=ColorZero.SHARED, dither=Dither.FAST))
result.save_image("out.png")
result.save_palette("out-palette.png")
print(result.indices.shape, result.palettes.shape)
```

## Параметры

| Параметр | Смысл |
|---|---|
| Ширина / высота тайла | размер тайла в пикселях (1–32) |
| Палитр | сколько палитр (1–16) |
| Цветов в палитре | сколько цветов в каждой (2–256), включая цвет с индексом 0 |
| Бит на канал | глубина цвета палитры: 5 для SNES/GBA, 3 для Mega Drive и т.д. |
| Доля пикселей | сколько случайных пикселей обрабатывается за итерацию; больше — точнее, но медленнее |
| Цвет с индексом 0 | *уникальный* — обычный цвет; *общий* — один и тот же заданный цвет во всех палитрах; *прозрачный* — индекс 0 зарезервирован под прозрачность (из альфа-канала или из заданного цвета-ключа) |
| Дизеринг | *быстрый* — дизеринг только при финальной отрисовке; *медленный* — учитывается и при подборе палитр |
| Паттерн дизеринга | упорядоченная матрица 2×2 на 4 или 2 уровня |

## Отличия от оригинала

Алгоритм перенесён один в один, качество совпадает с веб-версией. Исправлено несколько мелочей:

- В оригинале палитры сортируются только для картинки палитры, а BMP пишется в несортированном порядке,
  поэтому индексы в BMP не совпадали с картинкой палитры. Здесь оба файла используют один порядок.
- Сравнение с цветом-ключом прозрачности теперь идёт по исходным пикселям. В оригинале без дизеринга
  ключ сравнивался с уже округлённой до N бит картинкой, и цвет вроде `#123456` переставал находиться.
- В медленном дизеринге цвет палитры подтягивается к тому кандидату, который реально выбран
  (в оригинале из-за общего массива всегда брался последний кандидат).
- По умолчанию результат сохраняется в индексированный PNG с прозрачностью; BMP тоже доступен.

## Лицензия

MIT, как и оригинал (см. [LICENSE](LICENSE)). Алгоритм и веб-версия — © 2022
[rilden](https://github.com/rilden); порт на Python написан Claude (Anthropic). Пример изображения
`carina-nebula.png` взят из оригинального репозитория (снимок NASA/JWST).
