# AI Money Hunters v0.2

Поиск возможностей заработка → антискам → оценка чистой выгоды → задача нужному агенту → черновик предложения → учёт → Telegram.
**Система сама ничего не отправляет и не выводит деньги.** Доход учитывается только после ручного подтверждения (`/log_received`).

## Установка / обновление репозитория
1. Загрузите содержимое папки `money_hunters` в корень репозитория, заменяя файлы (в корне должны лежать `hunters/`, `tests/`, `.github/`, `run_cycle.py`, `sources.json`).
2. Settings → Secrets → Actions: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OWNER_ID`.
3. (Необязательно, ИИ для черновиков) GitHub Models работает автоматически в Actions. Или своё: secret `LLM_API_KEY`, variables `LLM_BASE_URL`, `LLM_MODEL` (любой OpenAI-совместимый API).
4. Actions → money-hunters → Run workflow. Состояние хранится в отдельной ветке `state` (история main не растёт).
5. Старый `data/mh.db` из main можно удалить: он больше не используется после первого запуска.

## Расписание
15 мин днём (08–20 по Душанбе) и раз в 2 часа ночью ≈ 1700 мин/мес из 2000 бесплатных для приватного репозитория. Запуск каждые 15 мин круглосуточно (≈2880 мин) бесплатный лимит превысит. Cron в GitHub не гарантирует точность. Команды Telegram обрабатываются на ближайшем запуске.

## Команды
/status /agents [A-F,S] /tasks /opportunities /earnings /received /pending /expenses /profit /top /report /errors /limits /pause /resume /approve /reject /history
/log_received /log_confirmed /log_pending /log_expense /log_hours /done /fail /draft /drafts /sources /source_on /source_off /notify /setprofile

## Источники (sources.json)
GitHub bounty-issues, Remotive API, RemoteOK API, We Work Remotely RSS, Reddit r/forhire. У каждого свой интервал опроса; после 5 ошибок подряд источник отключается (вернуть: `/source_on имя`).
