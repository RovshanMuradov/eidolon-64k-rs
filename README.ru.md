# Eidolon на Rust

Порт на Rust 64k-интро **Eidolon** группы Poo-Brain, победителя конкурса PC 64k на Revision 2017. Порт повторяет оригинал точно: при управляемом захвате все 27 000 кадров и вся музыка совпадают с оригинальным EXE побайтово.

English version: [README.md](README.md)

- Оригинал: [pouët](https://www.pouet.net/prod.php?which=69669) · [demozoo](https://demozoo.org/productions/170753/) · [scene.org](https://files.scene.org/view/parties/2017/revision17/pc_64k_intro/eidolon_-_poo-brain_-_revision2017_64k_-_rc4.zip) · [YouTube](https://youtu.be/rsZHBJdaz-Y)
- Как устроен оригинал: [docs/ru](docs/ru/README.md)

## Быстрый старт

```sh
make run
```

`make run` собирает программу и запускает интро. Несколько минут окно показывает экран загрузки, пока синтезируется вся музыка, затем 7,5 минуты идёт интро и программа завершается. Escape — выход.

| Команда | Что делает |
|---|---|
| `make build` | Собирает `target/i686-pc-windows-gnu/release/eidolon-runtime.exe` |
| `make run` | Собирает и запускает; `RES=1280x720 make run` меняет размер окна Wine |
| `make test` | Запускает тесты Rust на текущей системе |
| `make clean` | Удаляет результаты сборки и отдельный префикс Wine `.wine/` |

## Требования

Интро — 32-битная программа для Windows на OpenGL 4.5 и WinMM. В других системах она запускается через Wine.

| Система | Статус | Что нужно |
|---|---|---|
| Windows | напрямую | [rustup](https://rustup.rs), [MSYS2](https://www.msys2.org) с `pacman -S make mingw-w64-i686-gcc` |
| Linux | через Wine; проверено на Wine 11.17 с драйвером NVIDIA | rustup, `make`, MinGW-w64 для i686, Wine с поддержкой 32 бит |
| macOS | не поддерживается | OpenGL в macOS ограничен версией 4.1 |

Пакеты MinGW-w64: Arch `mingw-w64-gcc`, Debian/Ubuntu `gcc-mingw-w64-i686`, Fedora `mingw32-gcc`.

При первой сборке `rustup` сам ставит нужный тулчейн и цель `i686-pc-windows-gnu` из `rust-toolchain.toml`. Rust из пакетов дистрибутива без `rustup` под эту цель не соберёт. Драйверы Mesa должны работать, если дают OpenGL 4.5 compatibility profile, но это не проверялось.

## Структура

| Путь | Содержимое |
|---|---|
| `src/` | Движок, таймлайн, физика, рантайм OpenGL, окно Win32, вывод звука |
| `src/audio/` | Порт синтезатора 64klang2 и партитура |
| `src/data/` | Таблицы оригинала: таймлайн, кривые, uniform, граф рендера |
| `shaders/` | Фрагменты GLSL оригинала |
| `docs/` | Как устроен оригинальный бинарник, на русском и английском |
| `tools/`, `tests/`, `artifacts/` | Инструменты реверса, захвата и сверки и их сохранённые результаты |

## Авторы

**Eidolon** — Poo-Brain:

| Кто | Роль |
|---|---|
| Andro | Режиссура, шейдеры |
| Tropical Trevor | Код, инструменты, шейдеры |
| Wurstgetrank | Шейдеры |
| Glow | 2D, шрифт, шейдеры |
| Roeltje | Код физики |
| Punqtured | Музыка, саунд-дизайн |
| Virgill | Музыка, саунд-дизайн |
| Gopher | 64klang2, зерно, виньетка |
| Beftex | Со-режиссура, Andro-nerve-controller |
| Maikel | Концепт-арт |

Сэмплы инструментов в `src/audio/gmdls_samples.rs` взяты из Roland GM/GS Sound Set (`gm.dls`), © 1996 Roland Corporation.

## Лицензия

Код на Rust, инструменты и документация распространяются по лицензии [MIT](LICENSE-MIT) или [Apache-2.0](LICENSE-APACHE), на ваш выбор. Шейдеры, музыка, данные анимации и сэмплы принадлежат перечисленным выше авторам, и эти лицензии на них не распространяются.
