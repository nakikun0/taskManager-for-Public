def calculate(time):
    hour = time // 3600
    minute = time%3600 // 60
    second = time % 60
    timeData = f"{hour}時間{minute}分{second}秒"
    return timeData