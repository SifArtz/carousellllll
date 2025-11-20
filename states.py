from aiogram.dispatcher.filters.state import State, StatesGroup



class AddAccount(StatesGroup):
    email = State()
    app_password = State()
    name = State()
    proxy = State()


class SetToken(StatesGroup):
    token = State()


class SetDelay(StatesGroup):
    delay = State()


class SetPrompt(StatesGroup):
    prompt = State()


class UploadTaskFile(StatesGroup):
    waiting_file = State()


class ReplyMessage(StatesGroup):
    waiting_text = State()
