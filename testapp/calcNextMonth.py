import datetime
import calendar

tokyo_tz = datetime.timezone(datetime.timedelta(hours=9))
dt = datetime.datetime.now(tokyo_tz)

def calcNextMonth():
    if dt.month == 12:
        nextMonth = 1
        nextYear = dt.year + 1
        next_weekdey, nextNumDays = calendar.monthrange(nextYear, nextMonth)
    else:
        nextMonth = dt.month + 1
        nextYear = dt.year
        next_weekdey, nextNumDays = calendar.monthrange(dt.year, dt.month + 1)

    return nextYear, nextMonth, nextNumDays
