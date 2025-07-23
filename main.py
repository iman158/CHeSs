#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, render_template_string, request, jsonify, session
import chess
import chess.engine
import uuid
from datetime import datetime

# --- CONFIGURATION ---
# IMPORTANT: Update this path to where you have installed the Stockfish engine.
# Example for Linux/macOS (if installed via package manager): "/usr/bin/stockfish" or "/usr/local/bin/stockfish"
# Example for Windows: "C:/path/to/stockfish/stockfish.exe"
STOCKFISH_PATH = "/usr/bin/stockfish"

# --- FLASK APP INITIALIZATION ---
app = Flask(__name__)
app.secret_key = 'chess_game_secret_key_v2_2025_animated'

# --- GLOBAL VARIABLES ---
# In-memory storage for active games and the chess engine instance.
games = {}
engine = None

# --- HELPER FUNCTIONS ---

def initialize_engine():
    """Initializes the Stockfish engine. Exits if the engine cannot be found."""
    global engine
    try:
        engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
        print("Stockfish engine initialized successfully.")
    except FileNotFoundError:
        print(f"ERROR: Stockfish engine not found at '{STOCKFISH_PATH}'")
        print("Please install Stockfish and update the STOCKFISH_PATH variable in the script.")
        exit()

def board_to_2d_array(board):
    """Converts a chess.Board object to a 2D list for the frontend."""
    board_array = [[None for _ in range(8)] for _ in range(8)]
    for row in range(8):
        for col in range(8):
            square = chess.square(col, 7 - row) # chess.square maps col, row from bottom-left
            piece = board.piece_at(square)
            if piece:
                board_array[row][col] = piece.symbol()
    return board_array

def get_winner(board):
    """Determines the winner from the board's result."""
    if board.is_checkmate():
        result = board.result()
        if result == "1-0":
            return "white"
        elif result == "0-1":
            return "black"
    elif board.is_stalemate() or board.is_insufficient_material() or board.is_seventyfive_moves() or board.is_fivefold_repetition():
        return "draw"
    return None

def get_last_move(board):
    """Gets the start and end squares of the last move."""
    if not board.move_stack:
        return None
    last_move = board.peek()
    return {
        'from': [7 - chess.square_rank(last_move.from_square), chess.square_file(last_move.from_square)],
        'to': [7 - chess.square_rank(last_move.to_square), chess.square_file(last_move.to_square)],
    }

def game_state_to_dict(game_id):
    """Builds the dictionary of the current game state to send to the frontend."""
    if game_id not in games:
        return None

    game_session = games[game_id]
    board = game_session['board']

    # Format move history for the frontend
    move_history = []
    # Create a temporary board to replay moves for SAN notation
    temp_board = chess.Board()
    for move in board.move_stack:
        move_history.append(temp_board.san(move))
        temp_board.push(move)


    return {
        'board': board_to_2d_array(board),
        'current_player': 'white' if board.turn == chess.WHITE else 'black',
        'game_over': board.is_game_over(),
        'winner': get_winner(board),
        'move_history': move_history,
        'captured_pieces': game_session['captured_pieces'],
        'last_move': get_last_move(board),
        'is_check': board.is_check()
    }

# --- FLASK API ROUTES ---

@app.route('/')
def index():
    """Serves the main HTML page."""
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/new_game', methods=['POST'])
def new_game():
    """Starts a new game session."""
    game_id = str(uuid.uuid4())
    board = chess.Board()
    games[game_id] = {
        'board': board,
        'captured_pieces': {'white': [], 'black': []}
    }
    session['game_id'] = game_id

    return jsonify({
        'success': True,
        'game_id': game_id,
        'game_state': game_state_to_dict(game_id)
    })

@app.route('/api/move', methods=['POST'])
def make_move():
    """Handles a player's move and triggers the AI's response."""
    game_id = session.get('game_id')
    if not game_id or game_id not in games:
        return jsonify({'success': False, 'error': 'No active game'})

    game_session = games[game_id]
    board = game_session['board']
    data = request.get_json()

    # Create a move object from the frontend's coordinates
    from_square = chess.square(data['from_col'], 7 - data['from_row'])
    to_square = chess.square(data['to_col'], 7 - data['to_row'])
    move = chess.Move(from_square, to_square)

    # Handle pawn promotion (defaults to Queen)
    if board.piece_at(from_square) and board.piece_at(from_square).piece_type == chess.PAWN:
        if chess.square_rank(to_square) == 0 or chess.square_rank(to_square) == 7:
            move.promotion = chess.QUEEN

    # Validate and make the player's move
    if move in board.legal_moves:
        # Track captured piece
        if board.is_capture(move):
            captured_piece = board.piece_at(to_square) or board.piece_at(from_square) # en passant
            if captured_piece:
                game_session['captured_pieces']['white'].append(captured_piece.symbol())

        board.push(move)

        # Trigger AI move if the game is not over
        ai_moved = False
        if not board.is_game_over():
            result = engine.play(board, chess.engine.Limit(time=0.5))
            ai_move = result.move

            # Track captured piece by AI
            if board.is_capture(ai_move):
                captured_piece = board.piece_at(ai_move.to_square) or board.piece_at(ai_move.from_square)
                if captured_piece:
                    game_session['captured_pieces']['black'].append(captured_piece.symbol())

            board.push(ai_move)
            ai_moved = True

        return jsonify({
            'success': True,
            'game_state': game_state_to_dict(game_id),
            'ai_moved': ai_moved
        })
    else:
        return jsonify({'success': False, 'error': 'Invalid move'})

@app.route('/api/valid_moves', methods=['POST'])
def get_valid_moves():
    """Returns a list of valid moves for a selected piece."""
    game_id = session.get('game_id')
    if not game_id or game_id not in games:
        return jsonify({'success': False, 'error': 'No active game'})

    board = games[game_id]['board']
    data = request.get_json()
    row, col = data['row'], data['col']

    from_square = chess.square(col, 7 - row)
    valid_moves_coords = []

    for move in board.legal_moves:
        if move.from_square == from_square:
            to_row = 7 - chess.square_rank(move.to_square)
            to_col = chess.square_file(move.to_square)
            valid_moves_coords.append([to_row, to_col])

    return jsonify({
        'success': True,
        'valid_moves': valid_moves_coords
    })

@app.route('/api/undo', methods=['POST'])
def undo_move():
    """Undoes the last player move and the corresponding AI move."""
    game_id = session.get('game_id')
    if not game_id or game_id not in games:
        return jsonify({'success': False, 'error': 'No active game'})

    game_session = games[game_id]
    board = game_session['board']

    if len(board.move_stack) >= 2:
        # Undo AI move
        ai_move = board.pop()
        if board.is_capture(ai_move):
            if game_session['captured_pieces']['black']:
                game_session['captured_pieces']['black'].pop()

        # Undo Player move
        player_move = board.pop()
        if board.is_capture(player_move):
            if game_session['captured_pieces']['white']:
                game_session['captured_pieces']['white'].pop()

        return jsonify({
            'success': True,
            'game_state': game_state_to_dict(game_id)
        })
    else:
        return jsonify({'success': False, 'error': 'Cannot undo'})

@app.route('/api/game_state')
def get_game_state_route():
    """Gets the current full state of the game."""
    game_id = session.get('game_id')
    if not game_id or game_id not in games:
        return jsonify({'success': False, 'error': 'No active game'})

    return jsonify({
        'success': True,
        'game_state': game_state_to_dict(game_id)
    })

# --- HTML TEMPLATE (ENHANCED WITH ANIMATIONS & NEW UI) ---
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Python Chess Game - Enhanced UI</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700&display=swap');

        :root {
            --board-size: 560px;
            --square-size: calc(var(--board-size) / 8);
            --light-square: #f0d9b5;
            --dark-square: #b58863;
            --primary-glow: #00f6ff;
            --secondary-glow: #ff00c1;
            --valid-move-color: rgba(20, 220, 80, 0.4);
            --selected-color: rgba(30, 150, 255, 0.9);
            --last-move-color: rgba(255, 230, 0, 0.3);
            --check-color: rgba(255, 50, 50, 0.5);
            --animation-speed: 0.3s;
        }

        body {
            font-family: 'Poppins', sans-serif;
            margin: 0;
            padding: 20px;
            background: #1a0c2e;
            background-image: linear-gradient(160deg, #1a0c2e 0%, #3d1b59 100%);
            min-height: 100vh;
            color: white;
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .header {
            text-align: center;
            position: absolute;
            top: 20px;
            width: 100%;
        }

        .header h1 {
            margin: 0;
            font-size: 2.2em;
            font-weight: 700;
            text-shadow: 0 0 10px var(--primary-glow), 0 0 20px var(--primary-glow);
        }

        .game-container {
            display: flex;
            gap: 40px;
            justify-content: center;
            align-items: flex-start;
            flex-wrap: wrap;
            margin-top: 80px;
        }

        .chess-board-wrapper {
            position: relative;
        }

        .board {
            display: grid;
            grid-template-columns: repeat(8, var(--square-size));
            grid-template-rows: repeat(8, var(--square-size));
            width: var(--board-size);
            height: var(--board-size);
            border: 4px solid #4a3423;
            border-radius: 10px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.5), inset 0 0 15px rgba(0,0,0,0.3);
        }

        .square {
            width: var(--square-size);
            height: var(--square-size);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: calc(var(--square-size) * 0.7);
            user-select: none;
            position: relative;
            cursor: pointer;
        }

        .square.light { background-color: var(--light-square); }
        .square.dark { background-color: var(--dark-square); }

        .square .piece {
            transition: transform 0.1s ease-out;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
            z-index: 10;
        }
        
        .square.selected .piece {
            transform: scale(1.1);
            color: var(--selected-color);
            text-shadow: 0 0 15px var(--primary-glow);
        }

        .square.last-move-from, .square.last-move-to {
            background-color: var(--last-move-color) !important;
        }
        
        .square.in-check .piece {
            color: var(--check-color);
            animation: pulse-check 0.8s infinite alternate;
        }

        @keyframes pulse-check {
            to { text-shadow: 0 0 20px var(--check-color); }
        }

        .valid-move-indicator {
            position: absolute;
            width: 30%;
            height: 30%;
            background: var(--valid-move-color);
            border-radius: 50%;
            opacity: 0.8;
            pointer-events: none;
            transition: transform 0.2s;
        }
        .square:hover .valid-move-indicator {
            transform: scale(1.2);
        }

        .flying-piece {
            position: absolute;
            font-size: calc(var(--square-size) * 0.7);
            pointer-events: none;
            z-index: 100;
            transition: transform var(--animation-speed) ease-in-out;
        }

        .game-panel {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(15px);
            -webkit-backdrop-filter: blur(15px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: 25px;
            border-radius: 15px;
            width: 320px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.37);
        }

        .status {
            font-size: 1.2em;
            font-weight: 600;
            margin-bottom: 20px;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
            background: rgba(0,0,0,0.2);
            transition: all 0.3s ease;
        }
        .status.white-turn { border-left: 5px solid white; }
        .status.black-turn { border-left: 5px solid #888; }
        .status.game-over { border-left: 5px solid var(--primary-glow); text-shadow: 0 0 5px var(--primary-glow); }
        .status.ai-thinking { animation: pulse-ai 1.5s infinite; }

        @keyframes pulse-ai {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.7; transform: scale(1.02); }
        }

        .controls {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
        }

        .btn {
            flex-grow: 1;
            padding: 12px 20px;
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 8px;
            cursor: pointer;
            font-size: 1em;
            font-weight: 600;
            transition: all 0.2s ease;
            text-transform: uppercase;
            background: rgba(255,255,255,0.1);
            color: white;
        }
        .btn:hover:not(:disabled) {
            background: rgba(255,255,255,0.2);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        .btn:disabled { opacity: 0.4; cursor: not-allowed; }

        .move-history {
            height: 150px;
            overflow-y: auto;
            background: rgba(0,0,0,0.2);
            border-radius: 8px;
            padding: 10px 15px;
            margin-top: 20px;
        }
        h3 { 
            margin-top: 0; 
            margin-bottom: 10px;
            font-weight: 600;
            color: var(--primary-glow);
            text-shadow: 0 0 5px var(--primary-glow);
        }
        .move-list {
            display: grid;
            grid-template-columns: 2em 1fr 1fr;
            gap: 5px;
            font-family: monospace;
            font-size: 0.9em;
        }
        .move-item { padding: 2px 5px; border-radius: 4px; }
        .move-item.white { background: rgba(255,255,255,0.05); }
        .move-item.black { background: rgba(0,0,0,0.1); }
        .move-num { color: #aaa; }

        .captured-pieces { margin-top: 20px; }
        .captured-row {
            min-height: 30px;
            padding: 5px 10px;
            background: rgba(0,0,0,0.2);
            border-radius: 5px;
            font-size: 1.5em;
        }
        .captured-row strong { font-size: 0.7em; color: #ccc; font-weight: 400; }

        @media (max-width: 1024px) {
            body {
                flex-direction: column;
                padding: 10px;
            }
            .header { position: static; margin-bottom: 20px;}
            .game-container { margin-top: 0; gap: 20px; }
            :root { --board-size: 90vw; }
        }
        @media (max-width: 380px) {
            :root { --board-size: 94vw; }
            .game-panel { width: 94vw; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Python & Stockfish Chess</h1>
    </div>

    <div class="game-container">
        <div class="chess-board-wrapper">
            <div class="board" id="board"></div>
        </div>

        <div class="game-panel">
            <div class="status" id="status">Loading...</div>
            
            <div class="controls">
                <button class="btn" onclick="newGame()">New Game</button>
                <button class="btn" onclick="undoMove()" id="undoBtn">Undo</button>
            </div>

            <div class="captured-pieces">
                <h3>Captured by White</h3>
                <div class="captured-row" id="whiteCaptured"></div>
            </div>
            <div class="captured-pieces">
                <h3>Captured by Black</h3>
                <div class="captured-row" id="blackCaptured"></div>
            </div>

            <div class="move-history">
                <h3>Move History</h3>
                <div class="move-list" id="moveList"></div>
            </div>
        </div>
    </div>

    <script>
        const pieces = {
            'K': '♔', 'Q': '♕', 'R': '♖', 'B': '♗', 'N': '♘', 'P': '♙',
            'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟'
        };

        let gameState = null;
        let selectedSquare = null;
        let validMoves = [];
        let isPlayerTurn = true;

        async function apiCall(endpoint, method = 'POST', body = null) {
            try {
                const options = {
                    method: method,
                    headers: {'Content-Type': 'application/json'}
                };
                if (body) {
                    options.body = JSON.stringify(body);
                }
                const response = await fetch(endpoint, options);
                const data = await response.json();
                if (!data.success) {
                    throw new Error(data.error || 'API call failed');
                }
                return data;
            } catch (error) {
                console.error(`Error with ${endpoint}:`, error);
                alert(`An error occurred: ${error.message}`);
                return null;
            }
        }

        async function newGame() {
            const data = await apiCall('/api/new_game');
            if (data) {
                gameState = data.game_state;
                clearSelection();
                updateDisplay();
            }
        }

        async function makeMove(fromRow, fromCol, toRow, toCol) {
            if (!isPlayerTurn) return;

            isPlayerTurn = false;
            updateStatus();
            
            const fromSquareEl = document.querySelector(`[data-row='${fromRow}'][data-col='${fromCol}']`);
            const toSquareEl = document.querySelector(`[data-row='${toRow}'][data-col='${toCol}']`);
            
            await animatePieceMove(fromSquareEl, toSquareEl);
            
            const data = await apiCall('/api/move', 'POST', {
                from_row: fromRow, from_col: fromCol, to_row: toRow, to_col: toCol
            });

            if (data) {
                gameState = data.game_state;
                if (data.ai_moved && !gameState.game_over) {
                    const aiFrom = gameState.last_move.from;
                    const aiTo = gameState.last_move.to;
                    const aiFromSqEl = document.querySelector(`[data-row='${aiFrom[0]}'][data-col='${aiFrom[1]}']`);
                    const aiToSqEl = document.querySelector(`[data-row='${aiTo[0]}'][data-col='${aiTo[1]}']`);
                    await animatePieceMove(aiFromSqEl, aiToSqEl);
                }
            }
            
            isPlayerTurn = true;
            clearSelection();
            updateDisplay();
        }
        
        async function getValidMoves(row, col) {
            const data = await apiCall('/api/valid_moves', 'POST', {row, col});
            return data ? data.valid_moves : [];
        }

        async function undoMove() {
            if (!isPlayerTurn) return;
            const data = await apiCall('/api/undo');
            if (data) {
                gameState = data.game_state;
                clearSelection();
                updateDisplay();
            }
        }
        
        function animatePieceMove(fromSquareEl, toSquareEl) {
            return new Promise(resolve => {
                const boardEl = document.getElementById('board');
                const pieceEl = fromSquareEl.querySelector('.piece');
                if (!pieceEl) {
                    resolve();
                    return;
                }

                const flyingPiece = pieceEl.cloneNode(true);
                flyingPiece.classList.add('flying-piece');

                const fromRect = fromSquareEl.getBoundingClientRect();
                const toRect = toSquareEl.getBoundingClientRect();
                const boardRect = boardEl.getBoundingClientRect();

                flyingPiece.style.left = `${fromRect.left - boardRect.left}px`;
                flyingPiece.style.top = `${fromRect.top - boardRect.top}px`;
                
                boardEl.appendChild(flyingPiece);
                pieceEl.style.opacity = '0';

                requestAnimationFrame(() => {
                    flyingPiece.style.transform = `translate(${toRect.left - fromRect.left}px, ${toRect.top - fromRect.top}px)`;
                });

                flyingPiece.addEventListener('transitionend', () => {
                    flyingPiece.remove();
                    pieceEl.style.opacity = '1';
                    resolve();
                }, { once: true });
            });
        }

        async function handleSquareClick(row, col) {
            if (!gameState || gameState.game_over || !isPlayerTurn || gameState.current_player !== 'white') {
                return;
            }

            if (selectedSquare) {
                const [selectedRow, selectedCol] = selectedSquare;
                const isValid = validMoves.some(move => move[0] === row && move[1] === col);

                if (isValid) {
                    clearSelection(false); // don't redraw board yet
                    await makeMove(selectedRow, selectedCol, row, col);
                } else {
                    clearSelection();
                    const piece = gameState.board[row][col];
                    if (piece && piece.toUpperCase() === piece) {
                        await selectSquare(row, col);
                    }
                }
            } else {
                const piece = gameState.board[row][col];
                if (piece && piece.toUpperCase() === piece) {
                    await selectSquare(row, col);
                }
            }
        }

        async function selectSquare(row, col) {
            selectedSquare = [row, col];
            validMoves = await getValidMoves(row, col);
            updateBoard(); // Redraw to show selection
        }

        function clearSelection(redraw = true) {
            selectedSquare = null;
            validMoves = [];
            if (redraw) updateBoard();
        }

        function updateDisplay() {
            if (!gameState) return;
            updateBoard();
            updateStatus();
            updateMoveHistory();
            updateCapturedPieces();
        }

        function updateBoard() {
            const boardElement = document.getElementById('board');
            boardElement.innerHTML = '';
            
            const kingSquare = findKingSquare();

            for (let r = 0; r < 8; r++) {
                for (let c = 0; c < 8; c++) {
                    const square = document.createElement('div');
                    square.className = `square ${(r + c) % 2 === 0 ? 'light' : 'dark'}`;
                    square.dataset.row = r;
                    square.dataset.col = c;
                    square.onclick = () => handleSquareClick(r, c);

                    const pieceSymbol = gameState.board[r][c];
                    if (pieceSymbol) {
                        const piece = document.createElement('span');
                        piece.className = 'piece';
                        piece.textContent = pieces[pieceSymbol];
                        square.appendChild(piece);
                    }

                    if (selectedSquare && selectedSquare[0] === r && selectedSquare[1] === c) {
                        square.classList.add('selected');
                    }
                    
                    if (gameState.last_move) {
                        if (gameState.last_move.from[0] === r && gameState.last_move.from[1] === c) {
                            square.classList.add('last-move-from');
                        }
                        if (gameState.last_move.to[0] === r && gameState.last_move.to[1] === c) {
                           square.classList.add('last-move-to');
                        }
                    }
                    
                    if (gameState.is_check && r === kingSquare[0] && c === kingSquare[1]) {
                        square.classList.add('in-check');
                    }

                    if (validMoves.some(m => m[0] === r && m[1] === c)) {
                        const moveIndicator = document.createElement('div');
                        moveIndicator.className = 'valid-move-indicator';
                        square.appendChild(moveIndicator);
                    }
                    
                    boardElement.appendChild(square);
                }
            }
        }
        
        function findKingSquare() {
            if (!gameState.is_check) return null;
            const kingSymbol = gameState.current_player === 'white' ? 'K' : 'k';
            for (let r = 0; r < 8; r++) {
                for (let c = 0; c < 8; c++) {
                    if (gameState.board[r][c] === kingSymbol) {
                        return [r, c];
                    }
                }
            }
            return null;
        }

        function updateStatus() {
            const statusElement = document.getElementById('status');
            statusElement.className = 'status';

            if (!isPlayerTurn && !gameState.game_over) {
                statusElement.textContent = 'AI is thinking...';
                statusElement.classList.add('ai-thinking');
            } else if (gameState.game_over) {
                let message = 'Game Over';
                if (gameState.winner === 'draw') {
                    message = "It's a Draw!";
                } else {
                    message = `Checkmate - ${gameState.winner === 'white' ? 'White' : 'Black'} Wins!`;
                }
                statusElement.textContent = message;
                statusElement.classList.add('game-over');
            } else {
                statusElement.textContent = `${gameState.current_player === 'white' ? 'White' : 'Black'}'s Turn`;
                statusElement.classList.add(`${gameState.current_player}-turn`);
            }
            
            document.getElementById('undoBtn').disabled = gameState.move_history.length < 2 || !isPlayerTurn;
        }

        function updateMoveHistory() {
            const moveList = document.getElementById('moveList');
            moveList.innerHTML = '';
            
            for(let i = 0; i < gameState.move_history.length; i += 2) {
                const moveNum = document.createElement('div');
                moveNum.className = 'move-item move-num';
                moveNum.textContent = `${i/2 + 1}.`;
                moveList.appendChild(moveNum);

                const whiteMove = document.createElement('div');
                whiteMove.className = 'move-item white';
                whiteMove.textContent = gameState.move_history[i];
                moveList.appendChild(whiteMove);

                if (gameState.move_history[i+1]) {
                    const blackMove = document.createElement('div');
                    blackMove.className = 'move-item black';
                    blackMove.textContent = gameState.move_history[i+1];
                    moveList.appendChild(blackMove);
                }
            }
            moveList.scrollTop = moveList.scrollHeight;
        }

        function updateCapturedPieces() {
            document.getElementById('whiteCaptured').textContent = gameState.captured_pieces.black.map(p => pieces[p] || p).join(' ');
            document.getElementById('blackCaptured').textContent = gameState.captured_pieces.white.map(p => pieces[p] || p).join(' ');
        }

        window.addEventListener('load', newGame);
    </script>
</body>
</html>
'''

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    initialize_engine()
    if engine:
        print("Starting Python Chess Game Server...")
        print("Open your web browser and go to: http://127.0.0.1:5000")
        print("Press Ctrl+C to stop the server")
        app.run(debug=False, host='0.0.0.0', port=5000)
