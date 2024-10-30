import re


def check_string(s):
    # 正規表現パターン：数字またはカンマ
    pattern = r'^[0-9,]+$'

    # 文字列がパターンに一致するかチェック
    if re.match(pattern, s):
        return True
    else:
        return False
