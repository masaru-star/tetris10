import random
import string
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# ルームデータ管理
# rooms[room_id] = {
#    'host': sid,
#    'status': 'waiting' | 'playing',
#    'players': { sid: {'name': name, 'alive': True, 'rank': None} },
#    'dead_order': []  # 脱落順 (先に死んだ人が入る)
# }
rooms = {}

def generate_room_id():
    # 数字2文字 + 英大文字2文字 (例: 12AB)
    nums = ''.join(random.choices(string.digits, k=2))
    chars = ''.join(random.choices(string.ascii_uppercase, k=2))
    return nums + chars

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('create_room')
def on_create(data):
    name = data['name']
    room_id = generate_room_id()
    while room_id in rooms:
        room_id = generate_room_id()
    
    rooms[room_id] = {
        'host': request.sid,
        'status': 'waiting',
        'players': {
            request.sid: {'name': name, 'alive': True, 'rank': None}
        },
        'dead_order': []
    }
    join_room(room_id)
    emit('room_created', {'roomId': room_id, 'isHost': True})
    update_lobby(room_id)

@socketio.on('join_room')
def on_join(data):
    room_id = data['roomId'].upper()
    name = data['name']
    
    if room_id not in rooms:
        emit('error', {'msg': 'ルームが見つかりません'})
        return
    if rooms[room_id]['status'] != 'waiting':
        emit('error', {'msg': 'ゲームは既に進行中です'})
        return
    if len(rooms[room_id]['players']) >= 10:
        emit('error', {'msg': 'ルームが満員です'})
        return

    rooms[room_id]['players'][request.sid] = {'name': name, 'alive': True, 'rank': None}
    join_room(room_id)
    emit('room_joined', {'roomId': room_id, 'isHost': False})
    update_lobby(room_id)

def update_lobby(room_id):
    if room_id not in rooms: return
    player_list = [p['name'] for p in rooms[room_id]['players'].values()]
    emit('update_lobby', {'players': player_list}, room=room_id)

@socketio.on('start_game')
def on_start(data):
    room_id = data['roomId']
    if room_id in rooms and rooms[room_id]['host'] == request.sid:
        rooms[room_id]['status'] = 'playing'
        rooms[room_id]['dead_order'] = []
        # 全員の状態をリセット
        for sid in rooms[room_id]['players']:
            rooms[room_id]['players'][sid]['alive'] = True
        emit('game_start', room=room_id)

@socketio.on('send_garbage')
def on_garbage(data):
    room_id = data['roomId']
    lines = data['lines']
    if room_id not in rooms: return

    # 自分以外の生存プレイヤーを取得
    targets = [sid for sid, p in rooms[room_id]['players'].items() if sid != request.sid and p['alive']]
    
    if targets:
        target_sid = random.choice(targets)
        # 攻撃ロジック: 2ライン=1段, 3ライン=2段, 4ライン=4段
        garbage_amount = 0
        if lines == 2: garbage_amount = 1
        elif lines == 3: garbage_amount = 2
        elif lines >= 4: garbage_amount = 4
        
        if garbage_amount > 0:
            emit('receive_garbage', {'amount': garbage_amount}, room=target_sid)

@socketio.on('player_died')
def on_died(data):
    room_id = data['roomId']
    if room_id not in rooms: return
    
    # プレイヤーを死亡状態にする
    rooms[room_id]['players'][request.sid]['alive'] = False
    rooms[room_id]['dead_order'].append(rooms[room_id]['players'][request.sid]['name'])
    
    # 生存者数を確認
    alive_players = [sid for sid, p in rooms[room_id]['players'].items() if p['alive']]
    
    # 自分に観戦モードへの移行を通知
    emit('spectate_mode', room=request.sid)

    # 最後の一人になったら終了 (または全員死亡)
    if len(alive_players) <= 1:
        # 残った一人を優勝者として追加（もし居れば）
        winner_name = None
        if len(alive_players) == 1:
            winner_name = rooms[room_id]['players'][alive_players[0]]['name']
            rooms[room_id]['dead_order'].append(winner_name) # 最後に追加＝1位
        
        # 順位表作成 (dead_orderの逆順がランキング)
        ranking = list(reversed(rooms[room_id]['dead_order']))
        rooms[room_id]['status'] = 'waiting' # 待機状態に戻す
        emit('game_over', {'ranking': ranking}, room=room_id)

@socketio.on('update_board')
def on_update_board(data):
    # 観戦用に自分の盤面情報をルーム全体（または観戦者）に送る
    # ここではシンプルにルーム全体に送るが、クライアント側で選別する
    room_id = data['roomId']
    if room_id in rooms:
        emit('spectator_update', {
            'id': request.sid,
            'grid': data['grid'],
            'name': rooms[room_id]['players'][request.sid]['name']
        }, room=room_id)

@socketio.on('disconnect')
def on_disconnect():
    # 切断処理（簡易版）
    for rid, room in rooms.items():
        if request.sid in room['players']:
            del room['players'][request.sid]
            update_lobby(rid)
            break

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
