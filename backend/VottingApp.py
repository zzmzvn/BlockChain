from web3 import Web3
import json
import time
import sqlite3
from flask import Flask, render_template, request, jsonify, session, Response
from datetime import datetime
import os
from functools import wraps
import csv
from io import StringIO
import random

# Load config
current_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(os.path.dirname(current_dir), 'config.json')
with open(config_path, 'r') as config_file:
    config = json.load(config_file)

# Initialize Flask app with config
app = Flask(__name__, 
           template_folder=config['flask_app']['template_folder'],
           static_folder='../templates/static')
app.secret_key = config['flask_app']['secret_key']

# Connect to Ganache using config
w3 = Web3(Web3.HTTPProvider(config['blockchain']['ganache_url']))

# Get contract ABI and address from config
contract_abi = config['blockchain']['contract_abi']
CONTRACT_ADDRESS = Web3.to_checksum_address(config['blockchain']['contract_address'])

# Initialize contract
def init_contract():
    try:
        # Check if Ganache is connected
        if not w3.is_connected():
            raise Exception("Cannot connect to Ganache. Please make sure Ganache is running.")
            
        # Check if contract address is valid
        if not w3.is_address(CONTRACT_ADDRESS):
            raise Exception("Invalid contract address in config.json")
            
        # Get contract
        contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=contract_abi)
        
        # Verify contract exists
        try:
            # Try to call a view function to verify contract exists
            contract.functions.owner().call()
            return contract
        except Exception as e:
            raise Exception(f"Contract not found at {CONTRACT_ADDRESS}. Please verify the contract address.")
            
    except Exception as e:
        print(f"Error initializing contract: {str(e)}")
        raise

# Database connection using config
def get_db():
    try:
        # Get absolute path to database file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(os.path.dirname(current_dir), config['database']['sqlite_file'])
        
        print(f"Connecting to database at: {db_path}")
        
        if not os.path.exists(db_path):
            print(f"Warning: Database file does not exist at {db_path}")
            
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        raise

# Initialize database using config
def init_db():
    try:
        conn = get_db()
        print("Successfully connected to database")
        
        # Check if tables already exist
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = [table[0] for table in cursor.fetchall()]
        print(f"Existing tables: {existing_tables}")
        
        if 'polls' not in existing_tables:
            # Create polls table
            polls_columns = config['database']['tables']['polls']['columns']
            columns_sql = ', '.join(f"{col} {type}" for col, type in polls_columns.items())
            conn.execute(f'''
                CREATE TABLE IF NOT EXISTS polls (  
                    {columns_sql}
                )
            ''')
            print("Created polls table")
        
        if 'votes' not in existing_tables:
            # Create votes table
            votes_config = config['database']['tables']['votes']
            columns = votes_config['columns']
            constraints = votes_config['constraints']
            
            columns_sql = ', '.join(f"{col} {type}" for col, type in columns.items())
            foreign_key = constraints['foreign_key']['references']
            
            conn.execute(f'''
                CREATE TABLE IF NOT EXISTS votes (
                    {columns_sql},
                    FOREIGN KEY(poll_id) REFERENCES {foreign_key}
                )
            ''')
            print("Created votes table")
        
        conn.commit()
        conn.close()
        print("Database initialization completed successfully!")
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        raise

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'wallet_address' not in session:
            return jsonify({
                'success': False,
                'error': 'Authentication required'
            }), 401
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'wallet_address' not in session:
            return jsonify({
                'success': False,
                'error': 'Authentication required'
            }), 401
        
        # Get the first account from Ganache as admin
        try:
            w3 = Web3(Web3.HTTPProvider(config['blockchain']['ganache_url']))
            admin_address = w3.eth.accounts[0]  # First account in Ganache is admin
            
            print(f"Connected wallet: {session['wallet_address']}")
            print(f"Admin address: {admin_address}")
            
            if session['wallet_address'].lower() != admin_address.lower():
                return jsonify({
                    'success': False,
                    'error': f'Admin access required. Please use account {admin_address}'
                }), 403
            return f(*args, **kwargs)
        except Exception as e:
            print(f"Error checking admin status: {str(e)}")
            return jsonify({
                'success': False,
                'error': 'Error checking admin status'
            }), 500
            
    return decorated

@app.route('/')
def index():
    return render_template('index.html', config=config)

@app.route('/create_vote', methods=['POST'])
@require_admin
def create_vote():
    try:
        data = request.json
        contract = init_contract()
        
        # Convert address to checksum format
        creator_address = Web3.to_checksum_address(data['creator_address'])
        
        # Create vote on blockchain
        tx_hash = contract.functions.createVoting(
            data['title'],
            data['options'],
            int(data['start_time']),
            int(data['end_time'])
        ).transact({'from': creator_address})
        
        # Convert HexBytes to string
        tx_hash_str = tx_hash.hex()
        
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        poll_hash = tx_receipt['transactionHash'].hex()
        
        # Store in local database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO polls (title, start_time, end_time, options, created_by, poll_hash)
            VALUES (?, datetime(?), datetime(?), ?, ?, ?)
        ''', (
            data['title'],
            datetime.fromtimestamp(data['start_time']).isoformat(),
            datetime.fromtimestamp(data['end_time']).isoformat(),
            json.dumps(data['options']),
            creator_address,
            poll_hash
        ))
        poll_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'poll_id': poll_id,
            'poll_hash': poll_hash,
            'transaction_hash': tx_hash_str
        })
    except Exception as e:
        print(f"Error in create_vote: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/vote/<poll_id>')
def vote_page(poll_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM polls WHERE id = ?', (poll_id,))
    poll = cursor.fetchone()
    conn.close()
    
    if poll is None:
        return "Poll not found", 404
        
    return render_template('voting.html', poll_id=poll_id, poll=dict(poll), config=config)

@app.route('/submit_vote', methods=['POST'])
@require_auth
def submit_vote():
    try:
        data = request.json
        contract = init_contract()
        
        # Convert address to checksum format
        voter_address = Web3.to_checksum_address(data['voter_address'])
        
        # Submit vote to blockchain
        tx_hash = contract.functions.vote(
            data['option_index']
        ).transact({'from': voter_address})
        
        # Convert HexBytes to string
        tx_hash_str = tx_hash.hex()
        
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        vote_hash = tx_receipt['transactionHash'].hex()
        
        # Store vote in database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO votes (
                poll_id, voter_address, voter_name, 
                option_index, option_text, timestamp, 
                tx_hash, vote_hash
            )
            VALUES (?, ?, ?, ?, ?, datetime('now'), ?, ?)
        ''', (
            data['poll_id'],
            voter_address,
            data['voter_name'],
            data['option_index'],
            data['option_text'],
            tx_hash_str,
            vote_hash
        ))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'transaction_hash': tx_hash_str,
            'vote_hash': vote_hash
        })
    except Exception as e:
        print(f"Error in submit_vote: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/get_poll/<poll_id>')
def get_poll(poll_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get poll data
        cursor.execute('SELECT * FROM polls WHERE id = ?', (poll_id,))
        poll = cursor.fetchone()
        
        if poll is None:
            return jsonify({
                'success': False,
                'error': 'Poll not found'
            }), 404
        
        # Get vote counts
        cursor.execute('''
            SELECT option_index, COUNT(*) as count 
            FROM votes 
            WHERE poll_id = ? 
            GROUP BY option_index
        ''', (poll_id,))
        
        vote_counts = cursor.fetchall()
        conn.close()
        
        poll_dict = dict(poll)
        
        return jsonify({
            'success': True,
            'poll': poll_dict,
            'vote_counts': [dict(vc) for vc in vote_counts]
        })
    except Exception as e:
        print(f"Error in get_poll: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html', config=config)

@app.route('/api/dashboard')
def get_dashboard_data():
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get total polls
        cursor.execute('SELECT COUNT(*) FROM polls')
        total_polls = cursor.fetchone()[0]
        
        # Get active polls
        cursor.execute('''
            SELECT COUNT(*) FROM polls 
            WHERE datetime(end_time) > datetime('now')
            AND status = 'active'
        ''')
        active_polls = cursor.fetchone()[0]
        
        # Get total voters
        cursor.execute('SELECT COUNT(DISTINCT voter_address) FROM votes')
        total_voters = cursor.fetchone()[0]
        
        # Get completed polls
        cursor.execute('''
            SELECT COUNT(*) FROM polls 
            WHERE status = 'completed'
        ''')
        completed_polls = cursor.fetchone()[0]
        
        # Get active polls data
        cursor.execute('''
            SELECT p.*, COUNT(v.id) as total_votes
            FROM polls p
            LEFT JOIN votes v ON p.id = v.poll_id
            WHERE datetime(p.end_time) > datetime('now')
            AND p.status = 'active'
            GROUP BY p.id
            ORDER BY p.start_time DESC
        ''')
        active_polls_data = [dict(row) for row in cursor.fetchall()]
        
        # Get completed polls data
        cursor.execute('''
            SELECT p.*, COUNT(v.id) as total_votes,
                   r.winner_option,
                   r.winner_votes
            FROM polls p
            LEFT JOIN votes v ON p.id = v.poll_id
            LEFT JOIN results r ON p.id = r.poll_id
            WHERE p.status = 'completed'
            GROUP BY p.id
            ORDER BY p.end_time DESC
        ''')
        completed_polls_data = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        return jsonify({
            'success': True,
            'stats': {
                'total_polls': total_polls,
                'active_polls': active_polls,
                'total_voters': total_voters,
                'completed_polls': completed_polls
            },
            'active_polls': active_polls_data,
            'completed_polls': completed_polls_data
        })
    except Exception as e:
        print(f"Error getting dashboard data: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/poll/<poll_id>/details')
def get_poll_details(poll_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get poll data
        cursor.execute('''
            SELECT p.*, COUNT(v.id) as total_votes
            FROM polls p
            LEFT JOIN votes v ON p.id = v.poll_id
            WHERE p.id = ?
            GROUP BY p.id
        ''', (poll_id,))
        poll = cursor.fetchone()
        
        if not poll:
            return jsonify({
                'success': False,
                'error': 'Poll not found'
            }), 404
        
        # Get vote results
        cursor.execute('''
            SELECT option_text, COUNT(*) as votes
            FROM votes
            WHERE poll_id = ?
            GROUP BY option_text
            ORDER BY votes DESC
        ''', (poll_id,))
        results = [dict(row) for row in cursor.fetchall()]
        
        # Get recent voters
        cursor.execute('''
            SELECT voter_name, voter_address, option_text, timestamp
            FROM votes
            WHERE poll_id = ?
            ORDER BY timestamp DESC
            LIMIT 10
        ''', (poll_id,))
        recent_voters = [dict(row) for row in cursor.fetchall()]
        
        # Check if poll has ended and needs to be finalized
        poll_dict = dict(poll)
        end_time = datetime.fromisoformat(poll_dict['end_time'])
        
        if end_time <= datetime.now() and poll_dict['status'] == 'active':
            # Finalize poll results
            winning_option = results[0] if results else None
            
            cursor.execute('''
                INSERT INTO results (
                    poll_id, final_results, total_votes,
                    winner_option, winner_votes, completion_time
                ) VALUES (?, ?, ?, ?, ?, datetime('now'))
            ''', (
                poll_id,
                json.dumps(results),
                poll_dict['total_votes'],
                winning_option['option_text'] if winning_option else None,
                winning_option['votes'] if winning_option else 0
            ))
            
            # Update poll status
            cursor.execute('''
                UPDATE polls
                SET status = 'completed'
                WHERE id = ?
            ''', (poll_id,))
            
            conn.commit()
            poll_dict['status'] = 'completed'
        
        conn.close()
        
        return jsonify({
            'success': True,
            'poll': poll_dict,
            'results': results,
            'recent_voters': recent_voters
        })
    except Exception as e:
        print(f"Error getting poll details: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/compare_results/<poll_id>')
def compare_results(poll_id):
    try:
        # 1. Get data from blockchain
        contract = init_contract()
        blockchain_results = contract.functions.getResult().call()
        blockchain_title = blockchain_results[0]
        blockchain_options = blockchain_results[1]
        blockchain_counts = blockchain_results[2]
        
        # Format blockchain data
        blockchain_data = {
            'title': blockchain_title,
            'votes': dict(zip(blockchain_options, blockchain_counts))
        }
        
        # 2. Get data from SQL database
        conn = get_db()
        cursor = conn.cursor()
        
        # Get poll details
        cursor.execute('SELECT title, options FROM polls WHERE id = ?', (poll_id,))
        poll = cursor.fetchone()
        
        if not poll:
            return jsonify({
                'success': False,
                'error': 'Poll not found'
            }), 404
            
        # Get vote counts from SQL
        cursor.execute('''
            SELECT option_text, COUNT(*) as count
            FROM votes
            WHERE poll_id = ?
            GROUP BY option_text
        ''', (poll_id,))
        sql_votes = cursor.fetchall()
        
        # Format SQL data
        sql_data = {
            'title': poll['title'],
            'votes': {row['option_text']: row['count'] for row in sql_votes}
        }
        
        # 3. Compare the data
        comparison = {
            'blockchain_data': blockchain_data,
            'sql_data': sql_data,
            'matches': {
                'title': blockchain_data['title'] == sql_data['title'],
                'vote_counts': all(
                    blockchain_data['votes'].get(option) == sql_data['votes'].get(option)
                    for option in set(blockchain_data['votes'].keys()) | set(sql_data['votes'].keys())
                )
            }
        }
        
        # Add discrepancies if any
        discrepancies = []
        if not comparison['matches']['title']:
            discrepancies.append({
                'type': 'title_mismatch',
                'blockchain_value': blockchain_data['title'],
                'sql_value': sql_data['title']
            })
            
        for option in set(blockchain_data['votes'].keys()) | set(sql_data['votes'].keys()):
            blockchain_count = blockchain_data['votes'].get(option, 0)
            sql_count = sql_data['votes'].get(option, 0)
            if blockchain_count != sql_count:
                discrepancies.append({
                    'type': 'vote_count_mismatch',
                    'option': option,
                    'blockchain_count': blockchain_count,
                    'sql_count': sql_count
                })
        
        if discrepancies:
            comparison['discrepancies'] = discrepancies
            
        return jsonify({
            'success': True,
            'comparison': comparison
        })
        
    except Exception as e:
        print(f"Error comparing results: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/auth/connect', methods=['POST'])
def connect_wallet():
    try:
        data = request.json
        wallet_address = data.get('wallet_address')
        
        if not wallet_address:
            raise ValueError('Wallet address is required')
            
        # Validate Ethereum address format
        if not Web3.is_address(wallet_address):
            raise ValueError('Invalid Ethereum address')
            
        session['wallet_address'] = wallet_address
        return jsonify({
            'success': True,
            'wallet_address': wallet_address
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@app.route('/api/poll/<poll_id>/export', methods=['GET'])
@require_auth
def export_poll_results(poll_id):
    try:
        format = request.args.get('format', 'csv')
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get poll details
        cursor.execute('''
            SELECT p.*, COUNT(v.id) as total_votes
            FROM polls p
            LEFT JOIN votes v ON p.id = v.poll_id
            WHERE p.id = ?
            GROUP BY p.id
        ''', (poll_id,))
        poll = cursor.fetchone()
        
        if not poll:
            return jsonify({
                'success': False,
                'error': 'Poll not found'
            }), 404
            
        # Get vote results
        cursor.execute('''
            SELECT option_text, COUNT(*) as votes
            FROM votes
            WHERE poll_id = ?
            GROUP BY option_text
            ORDER BY votes DESC
        ''', (poll_id,))
        results = cursor.fetchall()
        
        # Get voter details
        cursor.execute('''
            SELECT voter_name, voter_address, option_text, timestamp
            FROM votes
            WHERE poll_id = ?
            ORDER BY timestamp DESC
        ''', (poll_id,))
        voters = cursor.fetchall()
        
        if format == 'csv':
            output = StringIO()
            writer = csv.writer(output)
            
            # Write poll info
            writer.writerow(['Poll Details'])
            writer.writerow(['Title', poll['title']])
            writer.writerow(['Start Time', poll['start_time']])
            writer.writerow(['End Time', poll['end_time']])
            writer.writerow(['Total Votes', poll['total_votes']])
            writer.writerow([])
            
            # Write results
            writer.writerow(['Results'])
            writer.writerow(['Option', 'Votes', 'Percentage'])
            for result in results:
                percentage = (result['votes'] / poll['total_votes'] * 100) if poll['total_votes'] > 0 else 0
                writer.writerow([
                    result['option_text'],
                    result['votes'],
                    f"{percentage:.2f}%"
                ])
            writer.writerow([])
            
            # Write voter details
            writer.writerow(['Voter Details'])
            writer.writerow(['Name', 'Address', 'Vote', 'Time'])
            for voter in voters:
                writer.writerow([
                    voter['voter_name'],
                    voter['voter_address'],
                    voter['option_text'],
                    voter['timestamp']
                ])
                
            output.seek(0)
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={
                    'Content-Disposition': f'attachment; filename=poll_{poll_id}_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
                }
            )
            
        else:
            return jsonify({
                'success': False,
                'error': 'Unsupported export format'
            }), 400
            
    except Exception as e:
        print(f"Error exporting results: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/poll/<poll_id>/compare')
@require_auth
def compare_poll_data(poll_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get poll data from SQL database
        cursor.execute('''
            SELECT p.*, r.final_results, r.winner_option, r.winner_votes
            FROM polls p
            LEFT JOIN results r ON p.id = r.poll_id
            WHERE p.id = ? AND p.status = 'completed'
        ''', (poll_id,))
        poll = cursor.fetchone()
        
        if not poll:
            return jsonify({
                'success': False,
                'error': 'Poll not found or not completed'
            }), 404
            
        # Get blockchain data
        contract = init_contract()
        blockchain_results = contract.functions.getResult().call()
        
        # Format data for comparison
        sql_data = {
            'title': poll['title'],
            'results': json.loads(poll['final_results']),
            'winner': {
                'option': poll['winner_option'],
                'votes': poll['winner_votes']
            }
        }
        
        blockchain_data = {
            'title': blockchain_results[0],
            'options': blockchain_results[1],
            'votes': blockchain_results[2],
            'winner': {
                'option': blockchain_results[1][blockchain_results[2].index(max(blockchain_results[2]))],
                'votes': max(blockchain_results[2])
            }
        }
        
        # Compare data
        matches = {
            'title': sql_data['title'] == blockchain_data['title'],
            'winner': (
                sql_data['winner']['option'] == blockchain_data['winner']['option'] and
                sql_data['winner']['votes'] == blockchain_data['winner']['votes']
            ),
            'vote_counts': True  # Will be updated in the loop below
        }
        
        discrepancies = []
        
        # Compare vote counts
        for option in set(blockchain_data['options']):
            sql_votes = next((r['votes'] for r in sql_data['results'] if r['option_text'] == option), 0)
            blockchain_votes = blockchain_data['votes'][blockchain_data['options'].index(option)]
            
            if sql_votes != blockchain_votes:
                matches['vote_counts'] = False
                discrepancies.append({
                    'option': option,
                    'sql_votes': sql_votes,
                    'blockchain_votes': blockchain_votes
                })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'comparison': {
                'sql_data': sql_data,
                'blockchain_data': blockchain_data,
                'matches': matches,
                'discrepancies': discrepancies
            }
        })
    except Exception as e:
        print(f"Error comparing poll data: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/poll/<poll_id>/manage', methods=['POST'])
@require_admin
def manage_poll(poll_id):
    try:
        data = request.json
        action = data.get('action')
        
        conn = get_db()
        cursor = conn.cursor()
        
        if action == 'archive':
            cursor.execute('''
                UPDATE polls 
                SET is_archived = 1, 
                    last_updated = datetime('now') 
                WHERE id = ?
            ''', (poll_id,))
            
        elif action == 'unarchive':
            cursor.execute('''
                UPDATE polls 
                SET is_archived = 0, 
                    last_updated = datetime('now') 
                WHERE id = ?
            ''', (poll_id,))
            
        elif action == 'finalize':
            # Verify poll is completed
            cursor.execute('SELECT status FROM polls WHERE id = ?', (poll_id,))
            poll = cursor.fetchone()
            if poll['status'] != 'completed':
                raise Exception('Cannot finalize active poll')
                
            # Calculate and store final results
            cursor.execute('''
                INSERT OR REPLACE INTO results (
                    poll_id, final_results, total_votes, 
                    winner_option, winner_votes, completion_time,
                    verification_hash, is_final
                )
                SELECT 
                    p.id,
                    json_group_array(
                        json_object(
                            'option_text', v.option_text,
                            'votes', COUNT(*),
                            'percentage', ROUND(CAST(COUNT(*) AS FLOAT) * 100 / p.total_votes, 2)
                        )
                    ),
                    p.total_votes,
                    first_value(v.option_text) OVER (
                        PARTITION BY p.id 
                        ORDER BY COUNT(*) DESC
                    ),
                    first_value(COUNT(*)) OVER (
                        PARTITION BY p.id 
                        ORDER BY COUNT(*) DESC
                    ),
                    datetime('now'),
                    hex(randomblob(16)),
                    1
                FROM polls p
                JOIN votes v ON p.id = v.poll_id
                WHERE p.id = ? AND v.vote_status = 'valid'
                GROUP BY p.id, v.option_text
            ''', (poll_id,))
            
        # Log action in history
        cursor.execute('''
            INSERT INTO vote_history (
                poll_id, action_type, action_data, 
                actor_address, tx_hash
            ) VALUES (?, ?, ?, ?, ?)
        ''', (
            poll_id,
            action,
            json.dumps(data),
            session['wallet_address'],
            data.get('tx_hash', '')
        ))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Poll {action} successful'
        })
        
    except Exception as e:
        print(f"Error in manage_poll: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/poll/<poll_id>/history')
@require_auth
def get_poll_history(poll_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get poll details
        cursor.execute('''
            SELECT p.*, r.final_results, r.is_final
            FROM polls p
            LEFT JOIN results r ON p.id = r.poll_id
            WHERE p.id = ?
        ''', (poll_id,))
        poll = cursor.fetchone()
        
        if not poll:
            return jsonify({
                'success': False,
                'error': 'Poll not found'
            }), 404
            
        # Get vote history
        cursor.execute('''
            SELECT v.*, vh.*
            FROM votes v
            LEFT JOIN vote_history vh ON v.poll_id = vh.poll_id
            WHERE v.poll_id = ?
            ORDER BY v.timestamp DESC, vh.action_timestamp DESC
        ''', (poll_id,))
        history = cursor.fetchall()
        
        conn.close()
        
        return jsonify({
            'success': True,
            'poll': dict(poll),
            'history': [dict(h) for h in history]
        })
        
    except Exception as e:
        print(f"Error in get_poll_history: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/poll/<poll_id>/stats')
@require_auth
def get_poll_stats(poll_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get poll statistics
        cursor.execute('''
            SELECT 
                p.*,
                r.final_results,
                r.is_final,
                COUNT(DISTINCT v.voter_address) as unique_voters,
                COUNT(DISTINCT vh.action_type) as total_actions
            FROM polls p
            LEFT JOIN results r ON p.id = r.poll_id
            LEFT JOIN votes v ON p.id = v.poll_id
            LEFT JOIN vote_history vh ON p.id = vh.poll_id
            WHERE p.id = ?
            GROUP BY p.id
        ''', (poll_id,))
        stats = cursor.fetchone()
        
        if not stats:
            return jsonify({
                'success': False,
                'error': 'Poll not found'
            }), 404
            
        # Get voting trends
        cursor.execute('''
            SELECT 
                strftime('%Y-%m-%d %H:00:00', timestamp) as hour,
                COUNT(*) as votes
            FROM votes
            WHERE poll_id = ? AND vote_status = 'valid'
            GROUP BY hour
            ORDER BY hour
        ''', (poll_id,))
        trends = cursor.fetchall()
        
        conn.close()
        
        return jsonify({
            'success': True,
            'stats': dict(stats),
            'trends': [dict(t) for t in trends]
        })
        
    except Exception as e:
        print(f"Error in get_poll_stats: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    init_db()
    app.run(
        debug=config['flask_app']['debug'],
        port=config['flask_app']['port']
    ) 