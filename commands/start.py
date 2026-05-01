from aiogram import Router
from aiogram.types import Message

# Commands

# Payment Gateways
_GATES_TEXT = "Commands: /st2, /b3-5, /pf0.6\n...other commands..."

# Full Help
_FULL_HELP = "Available commands: /st2, /b3-5, /pf0.6\n...other details..."

# Create router
router = Router()

# Register the /start command handler
@router.message.command("start")
async def start_handler(message: Message):
    await message.answer("Welcome! " + _FULL_HELP)