from datetime import datetime
import functools
from flask import Flask, render_template, request, redirect, url_for, flash, g, session, abort
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'desentupimento-do-barbosa-secret'
DATABASE = os.path.join(os.path.dirname(__file__), 'database.db')


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def get_user_by_username(username):
    return query_db('SELECT * FROM users WHERE username = ?', [username], one=True)


def init_db():
    db = get_db()
    db.execute('''
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            telefone TEXT,
            endereco TEXT,
            observacoes TEXT,
            criado_em TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS chamados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            data_chamado TEXT NOT NULL,
            horario TEXT NOT NULL,
            tipo_servico TEXT NOT NULL,
            status TEXT NOT NULL,
            valor_orcado REAL,
            observacoes TEXT,
            criado_em TEXT NOT NULL,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL
        )
    ''')
    db.commit()

    admin = query_db('SELECT * FROM users WHERE username = ?', ['admin'], one=True)
    if admin is None:
        db.execute('INSERT INTO users (username, password_hash, is_admin, active, criado_em) VALUES (?, ?, ?, ?, ?)',
                   ('admin', generate_password_hash('barbosa123'), 1, 1, datetime.now().isoformat()))
        db.commit()


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
        return
    user = query_db('SELECT * FROM users WHERE id = ?', [user_id], one=True)
    if user is None or user['active'] == 0:
        session.clear()
        g.user = None
        if user is not None and user['active'] == 0:
            flash('Sua conta foi desativada.', 'warning')
        return
    g.user = user


@app.before_request
def require_login():
    if request.endpoint in ('login', 'static'):
        return
    if g.user is None:
        return redirect(url_for('login'))


def admin_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None or not g.user['is_admin']:
            abort(403)
        return view(**kwargs)
    return wrapped_view


with app.app_context():
    init_db()


@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.user is not None:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = get_user_by_username(username)
        if not user or not check_password_hash(user['password_hash'], password):
            flash('Usuário ou senha incorretos.', 'danger')
            return redirect(url_for('login'))
        if not user['active']:
            flash('Conta desativada. Contate o administrador.', 'danger')
            return redirect(url_for('login'))
        session.clear()
        session['user_id'] = user['id']
        flash('Login realizado com sucesso.', 'success')
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Você saiu do sistema.', 'success')
    return redirect(url_for('login'))


@app.route('/usuarios')
@admin_required
def usuarios():
    users = query_db('SELECT * FROM users ORDER BY criado_em DESC')
    return render_template('usuarios.html', users=users)


@app.route('/usuarios/novo', methods=['GET', 'POST'])
@admin_required
def novo_usuario():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        is_admin = 1 if request.form.get('is_admin') == 'on' else 0
        if not username or not password:
            flash('Preencha usuário e senha.', 'danger')
            return redirect(url_for('novo_usuario'))
        if get_user_by_username(username):
            flash('Nome de usuário já existe.', 'danger')
            return redirect(url_for('novo_usuario'))
        db = get_db()
        db.execute('INSERT INTO users (username, password_hash, is_admin, active, criado_em) VALUES (?, ?, ?, ?, ?)',
                   (username, generate_password_hash(password), is_admin, 1, datetime.now().isoformat()))
        db.commit()
        flash('Usuário criado com sucesso.', 'success')
        return redirect(url_for('usuarios'))
    return render_template('novo_usuario.html')


@app.route('/usuarios/<int:user_id>/toggle', methods=['POST'])
@admin_required
def toggle_usuario(user_id):
    if g.user['id'] == user_id:
        flash('Você não pode desativar sua própria conta.', 'danger')
        return redirect(url_for('usuarios'))
    user = query_db('SELECT * FROM users WHERE id = ?', [user_id], one=True)
    if not user:
        flash('Usuário não encontrado.', 'warning')
        return redirect(url_for('usuarios'))
    new_active = 0 if user['active'] else 1
    db = get_db()
    db.execute('UPDATE users SET active = ? WHERE id = ?', (new_active, user_id))
    db.commit()
    flash('Status do usuário atualizado.', 'success')
    return redirect(url_for('usuarios'))


@app.route('/')
def index():
    total_clientes = query_db('SELECT COUNT(*) AS total FROM clientes', one=True)['total']
    total_chamados = query_db('SELECT COUNT(*) AS total FROM chamados', one=True)['total']
    pendentes = query_db("SELECT COUNT(*) AS total FROM chamados WHERE status != 'Concluído'", one=True)['total']
    sem_orcamento = query_db('SELECT COUNT(*) AS total FROM chamados WHERE valor_orcado IS NULL', one=True)['total']
    hoje = datetime.now().strftime('%Y-%m-%d')
    chamados_hoje = query_db('SELECT c.id, c.data_chamado, c.horario, cl.nome AS cliente, c.tipo_servico, c.status FROM chamados c JOIN clientes cl ON cl.id = c.cliente_id WHERE c.data_chamado = ? ORDER BY c.horario', [hoje])
    return render_template('index.html', total_clientes=total_clientes, total_chamados=total_chamados, pendentes=pendentes, sem_orcamento=sem_orcamento, chamados_hoje=chamados_hoje)


@app.route('/clientes')
def clientes():
    clientes = query_db('SELECT * FROM clientes ORDER BY criado_em DESC')
    return render_template('clientes.html', clientes=clientes)


@app.route('/clientes/novo', methods=['GET', 'POST'])
def novo_cliente():
    if request.method == 'POST':
        nome = request.form['nome'].strip()
        telefone = request.form.get('telefone', '').strip()
        endereco = request.form.get('endereco', '').strip()
        observacoes = request.form.get('observacoes', '').strip()
        if not nome:
            flash('O nome do cliente é obrigatório.', 'danger')
            return redirect(url_for('novo_cliente'))
        db = get_db()
        db.execute('INSERT INTO clientes (nome, telefone, endereco, observacoes, criado_em) VALUES (?, ?, ?, ?, ?)',
                   (nome, telefone, endereco, observacoes, datetime.now().isoformat()))
        db.commit()
        flash('Cliente cadastrado com sucesso!', 'success')
        return redirect(url_for('clientes'))
    return render_template('novo_cliente.html')


@app.route('/clientes/<int:cliente_id>')
def ver_cliente(cliente_id):
    cliente = query_db('SELECT * FROM clientes WHERE id = ?', [cliente_id], one=True)
    if not cliente:
        flash('Cliente não encontrado.', 'warning')
        return redirect(url_for('clientes'))
    chamados = query_db('SELECT * FROM chamados WHERE cliente_id = ? ORDER BY criado_em DESC', [cliente_id])
    return render_template('ver_cliente.html', cliente=cliente, chamados=chamados)


@app.route('/clientes/<int:cliente_id>/excluir', methods=['POST'])
def excluir_cliente(cliente_id):
    cliente = query_db('SELECT * FROM clientes WHERE id = ?', [cliente_id], one=True)
    if not cliente:
        flash('Cliente não encontrado.', 'warning')
        return redirect(url_for('clientes'))
    db = get_db()
    db.execute('DELETE FROM chamados WHERE cliente_id = ?', [cliente_id])
    db.execute('DELETE FROM clientes WHERE id = ?', [cliente_id])
    db.commit()
    flash('Cliente excluído com sucesso.', 'success')
    return redirect(url_for('clientes'))


@app.route('/chamados')
def chamados():
    chamados = query_db('SELECT c.*, cl.nome as cliente FROM chamados c JOIN clientes cl ON c.cliente_id = cl.id ORDER BY c.data_chamado, c.horario')
    return render_template('chamados.html', chamados=chamados)


@app.route('/chamados/novo', methods=['GET', 'POST'])
def novo_chamado():
    clientes = query_db('SELECT id, nome FROM clientes ORDER BY nome')
    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')
        data_chamado = request.form.get('data_chamado')
        horario = request.form.get('horario')
        tipo_servico = request.form.get('tipo_servico', '').strip()
        valor_orcado = request.form.get('valor_orcado')
        observacoes = request.form.get('observacoes', '').strip()
        if not cliente_id or not data_chamado or not horario or not tipo_servico:
            flash('Preencha todos os campos obrigatórios do chamado.', 'danger')
            return redirect(url_for('novo_chamado'))
        valor_orcado = float(valor_orcado) if valor_orcado else None
        db = get_db()
        db.execute('''INSERT INTO chamados (cliente_id, data_chamado, horario, tipo_servico, status, valor_orcado, observacoes, criado_em)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                   (cliente_id, data_chamado, horario, tipo_servico, 'Agendado', valor_orcado, observacoes, datetime.now().isoformat()))
        db.commit()
        flash('Chamado registrado com sucesso.', 'success')
        return redirect(url_for('chamados'))
    return render_template('novo_chamado.html', clientes=clientes)


@app.route('/chamados/<int:chamado_id>/editar', methods=['GET', 'POST'])
def editar_chamado(chamado_id):
    chamado = query_db('SELECT * FROM chamados WHERE id = ?', [chamado_id], one=True)
    if not chamado:
        flash('Chamado não encontrado.', 'warning')
        return redirect(url_for('chamados'))
    clientes = query_db('SELECT id, nome FROM clientes ORDER BY nome')
    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')
        data_chamado = request.form.get('data_chamado')
        horario = request.form.get('horario')
        tipo_servico = request.form.get('tipo_servico', '').strip()
        status = request.form.get('status')
        valor_orcado = request.form.get('valor_orcado')
        observacoes = request.form.get('observacoes', '').strip()
        if not cliente_id or not data_chamado or not horario or not tipo_servico or not status:
            flash('Preencha todos os campos obrigatórios.', 'danger')
            return redirect(url_for('editar_chamado', chamado_id=chamado_id))
        valor_orcado = float(valor_orcado) if valor_orcado else None
        db = get_db()
        db.execute('''UPDATE chamados SET cliente_id = ?, data_chamado = ?, horario = ?, tipo_servico = ?, status = ?, valor_orcado = ?, observacoes = ? WHERE id = ?''',
                   (cliente_id, data_chamado, horario, tipo_servico, status, valor_orcado, observacoes, chamado_id))
        db.commit()
        flash('Chamado atualizado com sucesso.', 'success')
        return redirect(url_for('chamados'))
    return render_template('editar_chamado.html', chamado=chamado, clientes=clientes)


@app.route('/relatorios')
def relatorios():
    chamados_sem_orcamento = query_db('SELECT c.*, cl.nome as cliente FROM chamados c JOIN clientes cl ON cl.id = c.cliente_id WHERE c.valor_orcado IS NULL ORDER BY c.data_chamado, c.horario')
    chamados_pendentes = query_db('SELECT c.*, cl.nome as cliente FROM chamados c JOIN clientes cl ON cl.id = c.cliente_id WHERE c.status != "Concluído" ORDER BY c.data_chamado, c.horario')
    return render_template('relatorios.html', chamados_sem_orcamento=chamados_sem_orcamento, chamados_pendentes=chamados_pendentes)


if __name__ == '__main__':
    app.run(debug=True, port=5000)
