from flask import Flask, render_template, request
from flask_socketio import SocketIO, join_room, leave_room, emit
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

games = {}
scores = {}

def check_winner(board):
    wins = [[0,1,2], [3,4,5], [6,7,8], [0,3,6], [1,4,7], [2,5,8], [0,4,8], [2,4,6]]
    for a,b,c in wins:
        if board[a] != '' and board[a] == board[b] == board[c]:
            return board[a]
    return None

def board_full(board):
    return all(cell != '' for cell in board)

@socketio.on('create_room')
def handle_create_room():
    room_id = str(uuid.uuid4())[:8]
    join_room(room_id)
    games[room_id] = {
        'board': [''] * 9,
        'turn': 'X',
        'players': [],
        'spectators': [],
        'winner': None,
        'game_over': False,
        'chat': []
    }
    emit('room_created', {'room': room_id})

@socketio.on('join_room')
def handle_join_room(data):
    room = data.get('room')
    name = data.get('name')
    if room not in games:
        emit('error_message', {'error': 'Room not found.'})
        return

    join_room(room)
    game = games[room]

    if any(p['sid'] == request.sid for p in game['players']):
        return

    if len(game['players']) < 2:
        symbol = 'X' if len(game['players']) == 0 else 'O'
        game['players'].append({'sid': request.sid, 'name': name, 'symbol': symbol})
        scores[name] = scores.get(name, 0)

        emit('joined_room', {
            'room': room,
            'symbol': symbol,
            'board': game['board'],
            'chat': game['chat'],
            'players': [{'name': p['name'], 'symbol': p['symbol']} for p in game['players']],
            'spectators': game['spectators'],
            'score': scores[name]
        })

        emit('update_board', {
            'board': game['board'],
            'message': f"Player {name} joined as {symbol}.",
            'next_turn': game['turn'],
            'game_over': False
        }, room=room)
    else:
        game['spectators'].append(name)
        emit('joined_as_spectator', {'name': name, 'spectators': game['spectators']}, room=room)

@socketio.on('make_move')
def handle_make_move(data):
    room = data.get('room')
    row, col = data.get('row'), data.get('col')

    if room not in games:
        emit('error_message', {'error': 'Invalid room.'})
        return
    game = games[room]

    if game['game_over']:
        emit('error_message', {'error': 'Game is over. Restart to play again.'})
        return

    idx = row * 3 + col
    board = game['board']
    if board[idx] != '':
        emit('error_message', {'error': 'Cell already taken.'})
        return

    player_sid = request.sid
    turn = game['turn']
    players = game['players']
    current_player = next((p for p in players if p['sid'] == player_sid), None)

    if not current_player or current_player['symbol'] != turn:
        emit('error_message', {'error': 'Not your turn.'})
        return

    board[idx] = turn
    winner = check_winner(board)

    if winner:
        game['winner'] = winner
        game['game_over'] = True
        scores[current_player['name']] += 1
        msg = f"{current_player['name']} ({winner}) wins!"
        next_turn = None
    elif board_full(board):
        game['winner'] = 'Tie'
        game['game_over'] = True
        msg = "It's a tie!"
        next_turn = None
    else:
        game['turn'] = 'O' if turn == 'X' else 'X'
        msg = f"Player {game['turn']}'s turn."
        next_turn = game['turn']

    emit('update_board', {
        'board': board,
        'message': msg,
        'next_turn': next_turn,
        'game_over': game['game_over']
    }, room=room)

@socketio.on('restart_game')
def handle_restart_game(data):
    room = data.get('room')
    if room not in games:
        emit('error_message', {'error': 'Invalid room.'})
        return
    game = games[room]
    game['board'] = [''] * 9
    game['turn'] = 'X'
    game['winner'] = None
    game['game_over'] = False
    emit('update_board', {
        'board': game['board'],
        'message': "Game restarted. Player X's turn.",
        'next_turn': 'X',
        'game_over': False
    }, room=room)

@socketio.on('send_message')
def handle_send_message(data):
    room = data.get('room')
    message = data.get('message')
    if room not in games or not message:
        return
    game = games[room]

    sender = next((p['name'] for p in game['players'] if p['sid'] == request.sid), 'Anonymous')
    chat_msg = {'name': sender, 'message': message}
    game['chat'].append(chat_msg)

    # Limit chat size
    if len(game['chat']) > 100:
        game['chat'].pop(0)

    # ✅ Emit only to players (not spectators)
    for player in game['players']:
        emit('receive_message', chat_msg, to=player['sid'])


@socketio.on('exit_room')
def handle_exit_room(data):
    room = data.get('room')
    name = data.get('name')
    if not room or room not in games:
        return
    game = games[room]

    emit('update_board', {
        'board': game['board'],
        'message': f"{name} left the game. Room will be closed.",
        'next_turn': None,
        'game_over': True
    }, room=room)

    emit('room_closed', room=room)

    del games[room]

@socketio.on('disconnect')
def handle_disconnect():
    for room, game in list(games.items()):
        for p in game['players']:
            if p['sid'] == request.sid:
                emit('update_board', {
                    'board': game['board'],
                    'message': f"{p['name']} disconnected. Room will be closed.",
                    'next_turn': None,
                    'game_over': True
                }, room=room)

                emit('room_closed', room=room)

                del games[room]
                return


@app.route('/', defaults={'room_id': None})
@app.route('/<room_id>')
def index(room_id):
    return render_template('index.html')

if __name__ == '__main__':
    socketio.run(app, debug=True)
