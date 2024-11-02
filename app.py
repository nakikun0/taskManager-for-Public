from flask import Flask, request, abort, render_template, jsonify, redirect, make_response, url_for
from dotenv import load_dotenv
import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    PushMessageRequest,
    ApiException
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    StickerMessageContent
)
from linebot import LineBotApi
from linebot.models import TextSendMessage
import datetime, calendar, time
from datetime import timedelta
from testapp.calcNextMonth import calcNextMonth
from sqlalchemy import create_engine, Column, Integer, String, MetaData, Table,\
    select, inspect, update, delete, JSON, ForeignKey
from sqlalchemy.sql import insert, select
from sqlalchemy.orm import sessionmaker
import copy
import json

# 初期設定
# ローカル開発環境でのみ dotenv を読み込む
if os.getenv('RENDER') is None:
    from dotenv import load_dotenv
    load_dotenv()
database_url = os.getenv('DATABASE_URL')
access_token = os.getenv('LINE_ACCESS_TOKEN')
webhook_handler = os.getenv('WEBHOOK_HANDLER')
developer_password = os.getenv('PASSWORD_FOR_DEVELOPER')
serviceurl = os.getenv("SERVICE_URL")

tokyo_tz = datetime.timezone(datetime.timedelta(hours=9))
dt = datetime.datetime.now(tokyo_tz)  # timezoneの設定

app = Flask(__name__)

configuration = Configuration(access_token=access_token)
handler = WebhookHandler(webhook_handler)  # ←チャンネルシークレット　↑チャンネルトークン
glb_line_bot_api = LineBotApi(access_token)


# データベースへの接続
engine = create_engine(database_url)

# テーブルの定義
metadata = MetaData()


users = Table('users', metadata,
              Column('id', Integer, primary_key=True, autoincrement=True),
              Column('name', String, unique=True),
              Column('line_id', String),
              )

shifts = Table("shifts", metadata,
               Column('id', Integer, primary_key=True, autoincrement=True),
               Column("userid", Integer, ForeignKey("users.id")),
               Column('shift', JSON),
               Column('next_month', JSON),
               )

events = Table("events", metadata,
               Column('id',Integer, primary_key=True, autoincrement=True),
               Column("userid", Integer, ForeignKey("users.id")),
               Column("title", String),
               Column("start", String),
               Column("end", String),
               Column("category", String),
               Column("comment", String)
               )

Learning_times = Table("Learning_times", metadata,
                     Column('id',Integer, primary_key=True, autoincrement=True),
                     Column("userid", Integer, ForeignKey("users.id")),
                     Column("learning_time", JSON)
                     )


# テーブルの作成
metadata.create_all(engine)

def upsert_shift_by_name(username, shift_data, next_month_data):

    Session = sessionmaker(bind=engine)
    session = Session()
    # 1. 名前から users テーブルの id を取得
    user = session.query(users).filter_by(name=username).first()
    
    if not user:
        print(f"Error: {username} という名前のユーザーが見つかりません")
        session.close()
        return  False
    
    user_id = user.id
    
    # 2. shifts テーブルで userid に基づいてデータを取得
    existing_shift = session.query(shifts).filter_by(userid=user_id).first()
    print(f"BEFORE:{existing_shift}\n\n")
    
    if existing_shift:
        # データが存在する場合は上書き
        update_stmt = (
            update(shifts).
            where(shifts.c.userid == user_id).
            values(shift=shift_data, next_month=next_month_data)
        )
        session.execute(update_stmt)
        print(f"{username} のシフトが正常に更新されました")
    else:
        # データが存在しない場合は追加
        insert_stmt = shifts.insert().values(
            userid=user_id,
            shift=shift_data,
            next_month=next_month_data
        )
        session.execute(insert_stmt)
        print(f"{username} のシフトが正常に保存されました")
    
    session.commit()
    session.close()
    return True


def upsert_events_by_name(username, title, start, end, category, comment):
    Session = sessionmaker(bind=engine)
    session = Session()
    # 1. 名前から users テーブルの id を取得
    user = session.query(users).filter_by(name=username).first()
    
    if not user:
        print(f"Error: {username} という名前のユーザーが見つかりません")
        session.close()
        return  False
    
    user_id = user.id

    existing_event = session.query(events).filter_by(
        userid=user_id,       # useridが一致
        title=title,         # titleが一致
        start=start,         # startが一致
        category=category    # categoryが一致
    ).first()

    print(f"既存のデータ：{existing_event}")

    if existing_event:
        update_stmt = (
            update(events).
            where(events.c.id == existing_event.id).
            values(userid=user_id, title=title, start=start, end=end, category=category, comment=comment)
        )
        session.execute(update_stmt)
        print(f"{username}のシフトが更新されました")
    else:
        insert_stmt = events.insert().values(
            userid=user_id,
            title=title,
            start=start,
            end=end,
            category=category,
            comment=comment
        )
        session.execute(insert_stmt)
        print(f"{username} のシフトが正常に保存されました")
    
    session.commit()
    session.close()
    return True

def getShiftData(name):
    Session = sessionmaker(bind=engine)
    session = Session()

    user = session.query(users).filter(users.c.name == name).first()

    if user:
        user_id = user.id
        shift = session.query(shifts).filter_by(userid=user_id).first()
        session.close()
        return shift
    else:
        session.close()
        return None  # レコードが見つからなかった場合


def checklearningTime(name):
    Session = sessionmaker(bind=engine)
    session = Session()

    user = session.query(users).filter(users.c.name == name).first()

    if user:
        user_id = user.id        
        Learning_times_content = session.query(Learning_times).filter_by(userid=user_id).all()
        for data in Learning_times_content:
            print(data)
    else:
        return None  # レコードが見つからなかった場合

def getEventdatas(name):
    Session = sessionmaker(bind=engine)
    session = Session()

    user = session.query(users).filter(users.c.name == name).first()
    if user:
        user_id = user.id
        events_content = session.query(events).filter_by(userid=user_id).all()
        session.close()
        return events_content
    else:
        session.close()
        return None

def deleteShiftdatas(name, id):
    Session = sessionmaker(bind=engine)
    session = Session()

    user = session.query(users).filter(users.c.name == name).first()

    if user:
        user_id = user.id
        shift = session.query(shifts).filter_by(userid=user_id).first()
        for shift_date in shift[2]:
            print("shift_date",shift_date)
            if shift_date["date"] == id:
                shift[2].remove(shift_date)
                print("match",shift[2])
                stmt = (
                    update(shifts).
                    where(shifts.c.userid == user_id).
                    values(shift=shift[2], next_month=shift[3])
                )
                break
        
        for shift_date in shift[3]:
            print("shift_date",shift_date)
            if shift_date["date"] == id:
                shift[3].remove(shift_date)
                print("match",shift[3])
                stmt = (
                    update(shifts).
                    where(shifts.c.userid == user_id).
                    values(shift=shift[2], next_month=shift[3])
                )
                break
        
        session.execute(stmt)
        session.commit()
        session.close()



def deleteEventdatas(id):
    Session = sessionmaker(bind=engine)
    session = Session()

    stmt = delete(events).where(events.c.id == id)
    session.execute(stmt)
    session.commit()
    session.close()

def sendMessage():
    todays_events = []
    today = str(dt.day)

    Session = sessionmaker(bind=engine)
    session = Session()

    rows = session.query(users).all() #全ユーザーのデータを取る
    for row in rows:

        messages = None
        todays_events = []
        todays_event = {"title":"", "start":None, "fin":None}
        name = row.name
        shift_Datas = getShiftData(name)
        if shift_Datas:
            if shift_Datas[2]: 
                for shift in shift_Datas[2]: # 今月のシフトデータから一致する日のものがあるか確認
                    if today == shift["date"]:
                        todays_event["title"] = "バイト"
                        if shift["start_time"]:
                            todays_event["start"] = shift["start_time"]
                        if shift["fin_time"]:
                            todays_event["fin"] = shift["fin_time"]
                        todays_events.append(todays_event.copy())
                        # print("OK")
                        break

        event_Datas = getEventdatas(name)
        if event_Datas: # スケジュール登録されたイベントデータから一致する日のものを探す
            for event in event_Datas:
                todays_event = {}
                # print(event)
                today = dt.strftime("%Y-%m-%d")
                # print("today",today)
                if today in event.start:
                    todays_event["title"] = event.title
                    if "T" in event.start:
                        todays_event["start"] = event.start[11:16]
                    if event.end:
                        todays_event["fin"] = event.end[11:16]
                    todays_events.append(todays_event.copy())
                    
        # print(todays_events)
        if todays_events:
            text = "今日の予定は\n"
            for todays_event in todays_events:
                print(todays_event)
                text += "・"+todays_event["title"]
                if todays_event["start"]:
                    text += " "+todays_event["start"]+"～"
                if todays_event["fin"]:
                    text += todays_event["fin"]
                text += "\n"
            text += "です\n\nカレンダーを確認する\n"+serviceurl+"calendar"

            messages = TextSendMessage(text=text)
            glb_line_bot_api.push_message(row.line_id,
                                      messages=messages)
            
    session.close()


def evening_sendMessage():
    nextday = str((dt + datetime.timedelta(days=1)).day)
    nextdays_events = []
    # print(nextday)

    Session = sessionmaker(bind=engine)
    session = Session()

    rows = session.query(users).all() #全ユーザーのデータを取る
    for row in rows:

        messages = None
        todays_events = []
        nextdays_event = {"title":"", "start":None, "fin":None}
        name = row.name
        shift_Datas = getShiftData(name)
        if shift_Datas: 
            if nextday == 1 and shift_Datas[3]:
                for shift in shift_Datas[3]: # 来月のシフトデータから一致する日のものがあるか確認
                    if nextday == shift["date"]:
                        nextdays_event["title"] = "バイト"
                        if shift["start_time"]:
                            nextdays_event["start"] = shift["start_time"]
                        if shift["fin_time"]:
                            nextdays_event["fin"] = shift["fin_time"]
                        nextdays_events.append(nextdays_event.copy())
                        # print("OK")
                        break
            else:
                if shift_Datas[2]:
                    for shift in shift_Datas[2]: # 今月のシフトデータから一致する日のものがあるか確認
                        if nextday == shift["date"]:
                            nextdays_event["title"] = "バイト"
                            if shift["start_time"]:
                                nextdays_event["start"] = shift["start_time"]
                            if shift["fin_time"]:
                                nextdays_event["fin"] = shift["fin_time"]
                            nextdays_events.append(nextdays_event.copy())
                            # print("OK")
                            break

        event_Datas = getEventdatas(name)
        if event_Datas: # スケジュール登録されたイベントデータから一致する日のものを探す
            for event in event_Datas:
                nextdays_event = {}
                # print(event)
                nextday = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
                # print("nextday",nextday)
                if nextday in event.start:
                    nextdays_event["title"] = event.title
                    if "T" in event.start:
                        nextdays_event["start"] = event.start[11:16]
                    if event.end:
                        nextdays_event["fin"] = event.end[11:16]
                    nextdays_events.append(nextdays_event.copy())
                    
        # print(nextdays_events)
        if nextdays_events:
            text = "明日の予定は\n"
            for nextdays_event in nextdays_events:
                # print(nextdays_event)
                text += "・"+nextdays_event["title"]
                if nextdays_event["start"]:
                    text += " "+nextdays_event["start"]+"～"
                if nextdays_event["fin"]:
                    text += nextdays_event["fin"]
                text += "\n"
            text += "です\n\nカレンダーを確認する\n"+serviceurl+"calendar"

            messages = TextSendMessage(text=text)
            glb_line_bot_api.push_message(row.line_id,
                                      messages=messages)
            
    session.close()


def change_month():
    Session = sessionmaker(bind=engine)
    session = Session()

    stmt = update(shifts).values(shift=shifts.c.next_month)
    session.execute(stmt)
    stmt = update(shifts).values(next_month=False).where(shifts.c.next_month.isnot(None))
    session.execute(stmt)
    session.commit()
    session.close()


scheduler = BackgroundScheduler()

morning_trigger = CronTrigger(hour=7, minute=0,
                              timezone=timezone('Asia/Tokyo'))
scheduler.add_job(sendMessage, morning_trigger)

evening_trigger = CronTrigger(hour=22, minute=0,
                              timezone=timezone('Asia/Tokyo'))
scheduler.add_job(evening_sendMessage, evening_trigger)

month_trigger = CronTrigger(day=1, hour=6, minute=58,
                            timezone=timezone('Asia/Tokyo'))
scheduler.add_job(change_month, month_trigger)  #月が変わったらシフトデータ更新

scheduler.start()

@app.route("/")
def tohome():
    return redirect(url_for("entrance"))

@app.route('/entrance', methods=['GET', 'POST'])
def entrance():
    nameisWrong = False
    if request.method == 'POST':
        line_name = request.form['name']
        Session = sessionmaker(bind=engine)
        session = Session()
        
        row = session.query(users).filter(users.c.name == line_name)
        row_first = row.first()

        # 同じ名前のユーザーがいた場合，cookieにnameを保存してリダイレクト
        if row_first:
            resp = make_response(redirect(url_for('dashboard')))
            resp.set_cookie('cookie_username', line_name, max_age=60*60*24)  # クッキーにユーザーIDを保存(1日)
            return resp
        nameisWrong = True
    return render_template("testapp/entrance.html", nameisWrong=nameisWrong)

@app.route("/dashboard")
def dashboard():
    cookie_username = request.cookies.get('cookie_username')  # クッキーからユーザーIDを取得
    if cookie_username:
        return render_template("testapp/index.html", cookie_username=cookie_username)
    else:
        return redirect(url_for("entrance"))

@app.route("/shift_resister", methods=["GET", "POST"])
def resister():
    weekdays_jp = ["月", "火", "水", "木", "金", "土", "日"]
    weekday, num_days = calendar.monthrange(dt.year, dt.month)
    current_month_weekdays = [weekdays_jp[(weekday + i) % 7] for i in range(num_days)] # 今月の各日の曜日を取得
    NextDates = calcNextMonth()

    next_weekday, next_num_days = calendar.monthrange(NextDates[0], NextDates[1])
    # 次の月の各日の曜日を取得
    next_month_weekdays = [weekdays_jp[(next_weekday + i) % 7] for i in range(NextDates[2])]

    return render_template("testapp/resister.html", year=dt.year,
                           month=dt.month, days=num_days, weekdays = current_month_weekdays,
                           next_month=NextDates[1],next_year=NextDates[0], next_days=NextDates[2],
                           next_weekdays = next_month_weekdays)


@app.route("/success", methods=["GET", "POST"])
def afterResister():
    name = request.form.get("username")
    print(name)
    dates = request.form.getlist('dates')
    NMdates = request.form.getlist('NMdates')
    shifts = []
    NMshifts = []

    for date in dates:
        start_time = request.form.get(f'start_time_{date}')
        fin_time = request.form.get(f'fin_time_{date}')
        shifts.append({
            'date': date,
            'start_time': start_time,
            'fin_time': fin_time
        })
        
    for date in NMdates:
        NMstart_time = request.form.get(f'NMstart_time_{date}')
        NMfin_time = request.form.get(f'NMfin_time_{date}')
        NMshifts.append({
            'date': date,
            'start_time': NMstart_time,
            'fin_time': NMfin_time
        })

    result = upsert_shift_by_name(name, shifts, NMshifts)
    return render_template("testapp/submitSuccess.html", result=result)
    

# 学習時間管理
@app.route("/learningTime",methods=['GET','POST'])
def resister_time():
    cookie_username = request.cookies.get('cookie_username')  # クッキーからユーザーIDを取得
    if cookie_username:
        checklearningTime(cookie_username)
        defaultDay = dt.strftime("%Y-%m-%d")
        current_time = dt.strftime("%Y/%m/%d %H:%M")
        return render_template('testapp/resister_time.html',today=defaultDay, current_time=current_time)
    else:
        return redirect(url_for("entrance"))

@app.route("/learningTime/success", methods=["GET", "POST"])
def lerningTimeSuccess():
    cookie_username = request.cookies.get('cookie_username')  # クッキーからユーザーIDを取得
    if cookie_username:
        result = False
        learningTime = {}
        learningTime["date"] = request.form.get("date")
        learningTime["time"] = request.form.get("time")
        learningTime["comment"] =request.form.get("comment")
        Session = sessionmaker(bind=engine)
        session = Session()
        # 1. 名前から users テーブルの id を取得
        user = session.query(users).filter_by(name=cookie_username).first()
        if user:
            user_id = user.id

            insert_stmt = Learning_times.insert().values(
                userid=user_id,
                learning_time = learningTime
                )
            session.execute(insert_stmt)
            session.commit()
            session.close()
            result = True

        return render_template("testapp/submitSuccess.html", result=result)
    else:
        return redirect(url_for("entrance"))


@app.route("/scheduleResister", methods=["POST", "GET"])
def scheduleResister():
    cookie_username = request.cookies.get('cookie_username')
    if cookie_username:
        return render_template("testapp/scheduleResister.html")
    else:
        return redirect(url_for("entrance"))

@app.route("/scheduleResister/success", methods=["POST", "GET"])
def scheduleSuccess():
    cookie_username = request.cookies.get('cookie_username')
    schedule_id = request.form.getlist("id")

    for i in schedule_id:
        title = request.form.get("title_"+i)
        date = request.form.get("date_"+i)
        if request.form.get("start_time_"+i):
            start = f'{date}T{request.form.get("start_time_"+i)}:00'
        else:
            start = date
        if request.form.get("fin_time_"+i):
            end = f'{date}T{request.form.get("fin_time_"+i)}:00'
        else:
            end = None
        category = request.form.get("category_"+i)
        comment = request.form.get("comment_"+i)
        if not comment:
            comment = None

        result = upsert_events_by_name(cookie_username, title, start, end, category, comment)
    
    return render_template("testapp/submitSuccess.html", result=result)

@app.route("/calendar", methods=["GET","POST"])
def checkCalendar():
    cookie_username = request.cookies.get('cookie_username')  # クッキーからユーザーIDを取得
    if cookie_username:
        # test = getEventdatas(cookie_username)
        return render_template("testapp/calendar.html", cookie_username=cookie_username)
    else:
        return redirect(url_for("entrance"))

@app.route('/get_events')
def get_events():
    cookie_username = request.cookies.get('cookie_username')

    # クエリパラメータで特定の日付を取得
    clicked_date = request.args.get('date')
    
    if clicked_date:

        # クリックされた日付のイベントを取得
        shift = getShiftData(cookie_username)
        clicked_event_details = []
        clicked_event_detail = {}
        this_month_shift = shift[2]
        next_month_shift = shift[3]
        # 日付が今月か翌月に含まれているかを確認
        month = str(dt.month).zfill(2)
        NextDates = calcNextMonth()
        next_month = str(NextDates[1]).zfill(2)
        next_year = NextDates[0]
        if this_month_shift:
            for shift_day in this_month_shift:  # クリックされた日付にバイトがあるか調べる
                day = str(shift_day["date"]).zfill(2)
                date = f"{dt.year}-{month}-{day}"
                if date == clicked_date:    # あればデータをリストに入れる
                    clicked_event_detail["title"] = "バイト"
                    if shift_day["start_time"]:
                        clicked_event_detail["start"] = shift_day["start_time"]
                    if shift_day["fin_time"]:
                        clicked_event_detail["fin"] = shift_day["fin_time"]
                    clicked_event_details.append(clicked_event_detail.copy())
                    break

        clicked_event_detail = {}

        if next_month_shift:
            for next_shift_day in next_month_shift:
                day = str(next_shift_day["date"]).zfill(2)
                date = f"{next_year}-{next_month}-{day}"
                if date == clicked_date:
                    clicked_event_detail["title"] = "バイト"
                    if shift_day["start_time"]:
                        clicked_event_detail["start"] = shift_day["start_time"]
                    if shift_day["fin_time"]:
                        clicked_event_detail["fin"] = shift_day["fin_time"].split("T")[1]
                    clicked_event_details.append(clicked_event_detail.copy())
                    break
        
        scheduled_events = getEventdatas(cookie_username)
        if scheduled_events:
            for sd_event in scheduled_events:   # eventsの中にクリックされた日付のものがあるか調べる
                clicked_event_detail = {}
                date = sd_event.start.split("T")[0]
                if date == clicked_date:    # あればリストに追加
                    clicked_event_detail["id"] =sd_event.id
                    clicked_event_detail["title"] = sd_event.title
                    if "T" in sd_event.start:
                        clicked_event_detail["start"] = sd_event.start.split("T")[1].rsplit(":",1)[0] # yyyy-mm-ddThh:mm:ssを hh:mmに変換
                    if sd_event.end:
                        clicked_event_detail["fin"] = sd_event.end.split("T")[1].rsplit(":",1)[0]
                    clicked_event_detail["category"] = sd_event.category
                    if sd_event.comment:
                        clicked_event_detail["comment"] = sd_event.comment
                    clicked_event_details.append(clicked_event_detail.copy())


        if clicked_event_details:
            clicked_event_details.insert(0,"success")
            return jsonify(clicked_event_details)   # リストをjson形式でhtmlに送信
        else:
            return jsonify(["error"])   # リストが空ならエラー
    else:
        events = []
        event = {}
        shift = getShiftData(cookie_username)
        NextDates = calcNextMonth()
        month = str(dt.month).zfill(2)
        next_month = str(NextDates[1]).zfill(2)
        next_year = NextDates[0]
        if shift[2]:
            for shift_day in shift[2]:
                event = {}
                day = str(shift_day["date"]).zfill(2)
                start = f"{dt.year}-{month}-{day}"
                event["allDay"] = True
                if shift_day["start_time"]:
                    start = f"{dt.year}-{month}-{day}T{shift_day['start_time']}"
                    event["allDay"] = False
                event["title"] = "バイト"
                event["start"] = start
                if shift_day["fin_time"]:
                    end = f"{dt.year}-{month}-{day}T{shift_day['fin_time']}"
                    event["end"] = end
                event["color"] = "green" 
                events.append(event.copy())

        if shift[3]:
            for shift_day in shift[3]:
                event = {}
                day = str(shift_day["date"]).zfill(2)
                start = f"{next_year}-{next_month}-{day}"
                event["allDay"] = True
                if shift_day["start_time"]:
                    start = f"{next_year}-{next_month}-{day}T{shift_day['start_time']}"
                    event["allDay"] = False
                event["title"] = "バイト"
                event["start"] = start
                if shift_day["fin_time"]:
                    end = f"{next_year}-{next_month}-{day}T{shift_day['fin_time']}"
                    event["end"] = end
                event["color"] = "green" 
                events.append(event.copy())

        scheduled_events = getEventdatas(cookie_username)
        if scheduled_events:
            for sd_event in scheduled_events:
                event = {}
                event["id"] = sd_event.id
                event["title"] = sd_event.title
                event["start"] = sd_event.start
                if sd_event.start:
                    event["end"] = sd_event.end
                event["category"] = sd_event.category
                if event["category"] == "就活":
                    event["color"] = "blue"
                elif event["category"] == "学業":
                    event["color"] = "red"
                else:
                    event["color"] = "yellow"
                event["comment"] = sd_event.category
                events.append(event.copy())

        # FullCalendar形式でイベントを返す
        return jsonify(events)

@app.route("/eventDeleted", methods=["POST", "GET"])
def eventDelete():
    cookie_username = request.cookies.get('cookie_username')
    event_id_list = request.form.getlist("eventCB")
    shift_id_list = request.form.getlist("shiftCB")
    for event_id in event_id_list:
        deleteEventdatas(event_id)

    for shift_id in shift_id_list:
        deleteShiftdatas(cookie_username, shift_id)

    return render_template("testapp/submitSuccess.html", result=True)


@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info(
            "Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'


@handler.add(MessageEvent,
             message=TextMessageContent)  # event.message.textは受け取ったメッセージ
def handle_message(event):
    userId = event.source.user_id

    profile = glb_line_bot_api.get_profile(event.source.user_id)
    name = profile.display_name
    found = False

    Session = sessionmaker(bind=engine)
    session = Session()

    # line_idのみを取得
    found = session.query(users).filter(users.c.line_id == userId).first()
    if not found:       #ユーザ情報が登録されていなければ新たに追加
        insert_stmt = users.insert().values(
            name = name,
            line_id = userId
        )
        session.execute(insert_stmt)
        session.commit()
    session.close()

    if event.message.text == "ありがとう":
        reply_message = "どういたしまして"

    elif event.message.text == "シフト登録":
        reply_message = f"{serviceurl}shift_resister"
    elif event.message.text == "スケジュール登録":
        reply_message = f"{serviceurl}scheduleResister"
    elif event.message.text == "カレンダー":
        reply_message = f"{serviceurl}calendar"
    else:
        reply_message = f'こんにちは\nシフトを登録したい場合「シフト登録」と送信してください'

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_message)]
            )
        )


@handler.add(MessageEvent, message=StickerMessageContent)
def handle_sticker_message(event):
    replymessage = "素敵なスタンプですね！"

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=replymessage)]
            )
        )


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000, debug=True)
