import asyncio
import sqlite3
import logging
from datetime import datetime, timedelta
from enum import Enum

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import ConflictingIdError
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, ConversationHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# === Конфигурация ===
TOKEN = "8117325876:AAFoCLi1Zp92akEQC3y5muM5gvqDlaC2SMo"
DB_NAME = "reminders.db"

# === Состояния ===
SET_TEXT, SET_DATE, SET_TIME = range(3)  # Для обычных напоминаний
SET_DURATION, SET_TIMER_TEXT = range(3, 5)  # Для таймеров
SET_REPEAT_INTERVAL, SET_REPEAT_DAYS = range(5, 7)  # Для повторяющихся напоминаний

# Типы повторений
class RepeatType(Enum):
    NONE = 0
    DAILY = 1
    WEEKLY = 2
    CUSTOM = 3


# === Логгирование ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ReminderBot:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        self.application = None

        # Добавляем периодическую очистку базы
        self.scheduler.add_job(
            self._cleanup_db_wrapper,
            'interval',
            hours=1,
            next_run_time=datetime.now() + timedelta(minutes=1)
        )

    @staticmethod
    def cleanup_db():
        """Статический метод для очистки базы данных"""
        with sqlite3.connect(DB_NAME) as conn:
            # Удаляем только разовые напоминания, которые прошли
            conn.execute("DELETE FROM reminders WHERE datetime(time) <= datetime('now') AND repeat_type = 0")
            conn.commit()

    def _cleanup_db_wrapper(self):
        """Обертка для вызова статического метода из планировщика"""
        self.cleanup_db()

    def h(self):
        with sqlite3.connect(DB_NAME) as conn:
            # Удаляем только разовые напоминания, которые прошли
            conn.execute("DELETE FROM reminders WHERE datetime(time) <= datetime('now') AND repeat_type = 0")
            conn.commit()

    def init_db(self):
        with sqlite3.connect(DB_NAME) as conn:
            # Создаем таблицу, если она не существует
            conn.execute("""
                         CREATE TABLE IF NOT EXISTS reminders
                         (
                             id
                             INTEGER
                             PRIMARY
                             KEY
                             AUTOINCREMENT,
                             user_id
                             INTEGER
                             NOT
                             NULL,
                             text
                             TEXT
                             NOT
                             NULL,
                             time
                             TEXT
                             NOT
                             NULL,
                             job_id
                             TEXT
                             NOT
                             NULL
                             UNIQUE,
                             is_timer
                             BOOLEAN
                             NOT
                             NULL
                             DEFAULT
                             FALSE,
                             repeat_type
                             INTEGER
                             NOT
                             NULL
                             DEFAULT
                             0,
                             repeat_interval
                             INTEGER,
                             next_run
                             TEXT
                         )
                         """)

            # Проверяем существующие столбцы и добавляем отсутствующие
            cursor = conn.execute("PRAGMA table_info(reminders)")
            columns = [column[1] for column in cursor.fetchall()]

            if 'repeat_type' not in columns:
                conn.execute("ALTER TABLE reminders ADD COLUMN repeat_type INTEGER NOT NULL DEFAULT 0")
            if 'repeat_interval' not in columns:
                conn.execute("ALTER TABLE reminders ADD COLUMN repeat_interval INTEGER")
            if 'next_run' not in columns:
                conn.execute("ALTER TABLE reminders ADD COLUMN next_run TEXT")

            # Удаляем просроченные разовые напоминания
            conn.execute("DELETE FROM reminders WHERE datetime(time) <= datetime('now') AND repeat_type = 0")
            conn.commit()

    async def send_reminder(self, user_id: int, text: str, job_id: str):
        try:
            await self.application.bot.send_message(
                chat_id=user_id,
                text=f"🔔 Напоминание: {text}"
            )

            with sqlite3.connect(DB_NAME) as conn:
                reminder = conn.execute(
                    "SELECT repeat_type, repeat_interval, time FROM reminders WHERE job_id = ?",
                    (job_id,)
                ).fetchone()

                if reminder and reminder[0] > 0:  # Если это повторяющееся напоминание
                    repeat_type = reminder[0]
                    interval = reminder[1]
                    last_run = datetime.fromisoformat(reminder[2])

                    if repeat_type == RepeatType.DAILY.value:
                        next_run = last_run + timedelta(days=1)
                    elif repeat_type == RepeatType.WEEKLY.value:
                        next_run = last_run + timedelta(weeks=1)
                    elif repeat_type == RepeatType.CUSTOM.value and interval:
                        next_run = last_run + timedelta(days=interval)
                    else:
                        next_run = None

                    if next_run:
                        # Обновляем время следующего выполнения в базе
                        conn.execute(
                            "UPDATE reminders SET time = ?, next_run = ? WHERE job_id = ?",
                            (next_run.isoformat(), next_run.isoformat(), job_id)
                        )
                        conn.commit()

                        # Планируем следующее выполнение
                        try:
                            self.scheduler.add_job(
                                self.sync_send_reminder,
                                'date',
                                run_date=next_run,
                                args=[user_id, text, job_id],
                                id=job_id
                            )
                        except ConflictingIdError:
                            logger.warning(f"Job {job_id} already exists, skipping")
                else:
                    # Удаляем разовое напоминание
                    conn.execute("DELETE FROM reminders WHERE job_id = ?", (job_id,))
                    conn.commit()
                    if self.scheduler.get_job(job_id):
                        self.scheduler.remove_job(job_id)

        except Exception as e:
            logger.error(f"Ошибка отправки напоминания: {e}")
            # Все равно пытаемся удалить
            with sqlite3.connect(DB_NAME) as conn:
                conn.execute("DELETE FROM reminders WHERE job_id = ?", (job_id,))
                conn.commit()
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)

    def sync_send_reminder(self, user_id: int, text: str, job_id: str):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self.send_reminder(user_id, text, job_id))
        except Exception as e:
            logger.error(f"Ошибка при отправке напоминания: {e}")
        finally:
            loop.close()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Привет! Я напомню тебе о важных делах.\n"
            "Команды:\n"
            "/remind — разовое напоминание на дату и время\n"
            "/repeat — повторяющееся напоминание (ежедневное, еженедельное или с интервалом)\n"
            "/timer — таймер через X времени\n"
            "/list — список напоминаний\n"
            "/cancel — отмена"
        )

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Отменяет текущий диалог и очищает данные"""
        # Проверяем, было ли уже обработано это сообщение
        if hasattr(context, '_cancel_processed') and context._cancel_processed:
            return ConversationHandler.END

        # Помечаем сообщение как обработанное
        context._cancel_processed = True

        user = update.effective_user
        logger.info("User %s canceled the conversation.", user.first_name)

        # Полная очистка данных пользователя
        context.user_data.clear()

        await update.message.reply_text(
            "❌ Все действия отменены. Вы можете начать заново.",
            reply_markup=ReplyKeyboardRemove()
        )

        return ConversationHandler.END

    async def start_remind(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("📝 Введите текст напоминания:")
        return SET_TEXT

    async def get_remind_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['text'] = update.message.text
        await update.message.reply_text("📅 Введите дату (ДД.ММ.ГГГГ):")
        return SET_DATE

    async def get_remind_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            datetime.strptime(update.message.text, "%d.%m.%Y")
            context.user_data['date'] = update.message.text
            await update.message.reply_text("⏰ Введите время (ЧЧ:ММ):")
            return SET_TIME
        except ValueError:
            await update.message.reply_text("❌ Неверный формат. Попробуйте ДД.ММ.ГГГГ")
            return SET_DATE

    async def get_remind_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            dt_str = f"{context.user_data['date']} {update.message.text}"
            remind_time = datetime.strptime(dt_str, "%d.%m.%Y %H:%M")

            if remind_time <= datetime.now():
                await update.message.reply_text("❌ Время уже прошло!")
                return ConversationHandler.END

            job_id = f"rem_{update.effective_user.id}_{datetime.now().timestamp()}"

            with sqlite3.connect(DB_NAME) as conn:
                conn.execute(
                    "INSERT INTO reminders VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (update.effective_user.id, context.user_data['text'],
                     remind_time.isoformat(), job_id, False,
                     RepeatType.NONE.value, None, None)
                )
                conn.commit()

            self.scheduler.add_job(
                self.sync_send_reminder, 'date',
                run_date=remind_time,
                args=[update.effective_user.id, context.user_data['text'], job_id],
                id=job_id
            )

            await update.message.reply_text(f"✅ Напоминание установлено на {remind_time.strftime('%d.%m.%Y %H:%M')}")
            return ConversationHandler.END
        except ValueError:
            await update.message.reply_text("❌ Неверный формат. Попробуйте ЧЧ:ММ")
            return SET_TIME

    async def start_repeat_reminder(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("📝 Введите текст напоминания:")
        return SET_TEXT

    async def get_repeat_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['text'] = update.message.text
        await update.message.reply_text(
            "📅 Введите дату первого напоминания (ДД.ММ.ГГГГ):"
        )
        return SET_DATE

    async def get_repeat_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            datetime.strptime(update.message.text, "%d.%m.%Y")
            context.user_data['date'] = update.message.text
            await update.message.reply_text("⏰ Введите время (ЧЧ:ММ):")
            return SET_TIME
        except ValueError:
            await update.message.reply_text("❌ Неверный формат. Попробуйте ДД.ММ.ГГГГ")
            return SET_DATE

    async def get_repeat_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            dt_str = f"{context.user_data['date']} {update.message.text}"
            first_run = datetime.strptime(dt_str, "%d.%m.%Y %H:%M")

            if first_run <= datetime.now():
                await update.message.reply_text("❌ Время уже прошло!")
                return ConversationHandler.END

            context.user_data['first_run'] = first_run

            keyboard = [
                [InlineKeyboardButton("Ежедневно", callback_data="daily")],
                [InlineKeyboardButton("Еженедельно", callback_data="weekly")],
                [InlineKeyboardButton("С интервалом (в днях)", callback_data="custom")]
            ]

            await update.message.reply_text(
                "🔄 Выберите тип повторения:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SET_REPEAT_INTERVAL
        except ValueError:
            await update.message.reply_text("❌ Неверный формат. Попробуйте ЧЧ:ММ")
            return SET_TIME

    async def set_repeat_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        repeat_type = query.data
        context.user_data['repeat_type'] = repeat_type
        first_run = context.user_data['first_run']
        text = context.user_data['text']

        if repeat_type == "custom":
            await query.edit_message_text("🔢 Введите интервал в днях (например, 2 для напоминания каждые 2 дня):")
            return SET_REPEAT_DAYS
        else:
            # Устанавливаем интервал автоматически
            interval = 1 if repeat_type == "daily" else 7
            context.user_data['interval'] = interval

            # Формируем текст подтверждения
            repeat_text = "каждый день" if repeat_type == "daily" else "каждую неделю"
            confirm_text = f"✅ Повторяющееся напоминание установлено на {first_run.strftime('%d.%m.%Y %H:%M')} ({repeat_text})"

            # Обновляем сообщение с подтверждением
            await query.edit_message_text(confirm_text)

            # Сохраняем напоминание
            return await self.save_repeat_reminder(update, context)

    async def set_repeat_days(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            interval = int(update.message.text)
            if interval < 1:
                raise ValueError

            context.user_data['interval'] = interval
            first_run = context.user_data['first_run']
            text = context.user_data['text']

            # Формируем текст подтверждения
            repeat_text = f"каждые {interval} дней"
            confirm_text = f"✅ Повторяющееся напоминание установлено на {first_run.strftime('%d.%m.%Y %H:%M')} ({repeat_text})"

            await update.message.reply_text(confirm_text)
            return await self.save_repeat_reminder(update, context)
        except:
            await update.message.reply_text("❌ Неверный формат. Введите число больше 0")
            return SET_REPEAT_DAYS

    async def save_repeat_reminder(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        first_run = context.user_data['first_run']
        text = context.user_data['text']
        user_id = update.effective_user.id if hasattr(update, 'effective_user') else update.message.from_user.id
        job_id = f"repeat_{user_id}_{datetime.now().timestamp()}"

        repeat_type = context.user_data['repeat_type']
        interval = context.user_data.get('interval', 1)

        with sqlite3.connect(DB_NAME) as conn:
            conn.execute(
                "INSERT INTO reminders VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, text, first_run.isoformat(), job_id, False,
                 RepeatType.DAILY.value if repeat_type == "daily" else RepeatType.WEEKLY.value if repeat_type == "weekly" else RepeatType.CUSTOM.value,
                 interval, first_run.isoformat())
            )
            conn.commit()

        self.scheduler.add_job(
            self.sync_send_reminder, 'date',
            run_date=first_run,
            args=[user_id, text, job_id],
            id=job_id
        )

        context.user_data.clear()
        return ConversationHandler.END

    async def start_timer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Введите длительность (например: 30s, 5m, 1h):")
        return SET_DURATION

    async def get_timer_duration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            txt = update.message.text.lower()
            if txt.endswith('s'):
                delta = timedelta(seconds=int(txt[:-1]))
            elif txt.endswith('m'):
                delta = timedelta(minutes=int(txt[:-1]))
            elif txt.endswith('h'):
                delta = timedelta(hours=int(txt[:-1]))
            else:
                raise ValueError
            context.user_data['delta'] = delta
            await update.message.reply_text("📝 Введите текст напоминания:")
            return SET_TIMER_TEXT
        except:
            await update.message.reply_text("❌ Неверный формат. Пример: 5m, 30s, 1h")
            return SET_DURATION

    async def get_timer_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        remind_time = datetime.now() + context.user_data['delta']
        job_id = f"timer_{update.effective_user.id}_{datetime.now().timestamp()}"

        with sqlite3.connect(DB_NAME) as conn:
            conn.execute(
                "INSERT INTO reminders VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)",
                (update.effective_user.id, update.message.text,
                 remind_time.isoformat(), job_id, True,
                 RepeatType.NONE.value, None, None)
            )
            conn.commit()

        self.scheduler.add_job(
            self.sync_send_reminder, 'date',
            run_date=remind_time,
            args=[update.effective_user.id, update.message.text, job_id],
            id=job_id
        )

        await update.message.reply_text(f"⏳ Таймер установлен! Напомню через {context.user_data['delta']}")
        return ConversationHandler.END

    async def list_reminders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        with sqlite3.connect(DB_NAME) as conn:
            # Удаляем просроченные разовые напоминания
            conn.execute("DELETE FROM reminders WHERE datetime(time) <= datetime('now') AND repeat_type = 0")
            conn.commit()

            # Получаем все активные напоминания
            reminders = conn.execute("""
                                     SELECT text, time, job_id, is_timer, repeat_type, repeat_interval
                                     FROM reminders
                                     WHERE user_id = ? AND (datetime(time) > datetime('now') OR repeat_type > 0)
                                     ORDER BY time
                                     """, (user_id,)).fetchall()

        if not reminders:
            await update.message.reply_text("📭 У вас нет активных напоминаний.")
            return

        msg = "📋 Ваши напоминания:\n\n"
        keyboard = []
        for text, time_str, job_id, is_timer, repeat_type, interval in reminders:
            dt = datetime.fromisoformat(time_str)

            if is_timer:
                time_desc = f"через {str(dt - datetime.now()).split('.')[0]}"
            elif repeat_type == RepeatType.DAILY.value:
                time_desc = f"ежедневно в {dt.strftime('%H:%M')} (след.: {dt.strftime('%d.%m.%Y')})"
            elif repeat_type == RepeatType.WEEKLY.value:
                time_desc = f"еженедельно по {dt.strftime('%A')} в {dt.strftime('%H:%M')} (след.: {dt.strftime('%d.%m.%Y')})"
            elif repeat_type == RepeatType.CUSTOM.value and interval:
                time_desc = f"каждые {interval} дней в {dt.strftime('%H:%M')} (след.: {dt.strftime('%d.%m.%Y')})"
            else:
                time_desc = dt.strftime('%d.%m.%Y %H:%M')

            msg += f"{'⏰' if not is_timer else '⏳'} {time_desc} — {text}\n"
            keyboard.append([InlineKeyboardButton(f"❌ Удалить: {text[:15]}...", callback_data=f"del_{job_id}")])

        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

    async def delete_reminder(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        job_id = query.data.split("_", 1)[1]
        user_id = query.from_user.id

        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM reminders WHERE job_id = ? AND user_id = ?", (job_id, user_id))
            conn.commit()

        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        await query.edit_message_text("❌ Напоминание удалено.")
        await self.list_reminders(update, context)

    def run(self):
        self.init_db()

        app = Application.builder().token(TOKEN).build()
        self.application = app

        # Убираем глобальный обработчик cancel

        # Обычные команды
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("list", self.list_reminders))
        app.add_handler(CallbackQueryHandler(self.delete_reminder, pattern=r"^del_"))

        # Обработчики ConversationHandler с общим fallback
        cancel_handler = CommandHandler("cancel", self.cancel)

        conv_handler_remind = ConversationHandler(
            entry_points=[CommandHandler("remind", self.start_remind)],
            states={
                SET_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_remind_text)],
                SET_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_remind_date)],
                SET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_remind_time)],
            },
            fallbacks=[cancel_handler],
        )

        conv_handler_repeat = ConversationHandler(
            entry_points=[CommandHandler("repeat", self.start_repeat_reminder)],
            states={
                SET_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_repeat_text)],
                SET_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_repeat_date)],
                SET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_repeat_time)],
                SET_REPEAT_INTERVAL: [CallbackQueryHandler(self.set_repeat_type)],
                SET_REPEAT_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_repeat_days)],
            },
            fallbacks=[cancel_handler],
        )

        conv_handler_timer = ConversationHandler(
            entry_points=[CommandHandler("timer", self.start_timer)],
            states={
                SET_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_timer_duration)],
                SET_TIMER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_timer_text)],
            },
            fallbacks=[cancel_handler],
        )

        app.add_handler(conv_handler_remind)
        app.add_handler(conv_handler_repeat)
        app.add_handler(conv_handler_timer)

        # Загружаем активные задачи из базы
        with sqlite3.connect(DB_NAME) as conn:
            for user_id, text, time_str, job_id, is_timer, repeat_type, interval, next_run in conn.execute(
                    "SELECT user_id, text, time, job_id, is_timer, repeat_type, repeat_interval, next_run "
                    "FROM reminders WHERE datetime(time) > datetime('now') OR repeat_type > 0"
            ).fetchall():
                dt = datetime.fromisoformat(time_str)
                try:
                    self.scheduler.add_job(
                        self.sync_send_reminder, 'date',
                        run_date=dt,
                        args=[user_id, text, job_id],
                        id=job_id
                    )
                except ConflictingIdError:
                    logger.warning(f"Job with id {job_id} already exists, skipping")

        print("Бот запущен!")
        app.run_polling()


if __name__ == "__main__":
    ReminderBot().run()