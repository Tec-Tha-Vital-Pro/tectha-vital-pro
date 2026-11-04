"""Daily owner briefing: the 9 am WhatsApp report (built in app/automations.py), shown in AI Labs so it
can be switched on and off in one place. It raises no findings."""
from datetime import datetime

from app.agents import Agent, register


def run(now: datetime) -> list[dict]:
    return []


register(Agent("owner_briefing", "Daily owner briefing",
               "Sends the owner yesterday's numbers for every branch on WhatsApp at 9 am, with AI insights when AI is on.",
               1440, run))
