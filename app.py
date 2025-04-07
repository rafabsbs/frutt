from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from twilio.rest import Client
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from flask_migrate import Migrate
from datetime import datetime
import os

# Configurações Twilio (obtenha em twilio.com)
load_dotenv()

app = Flask(__name__)

DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL

app.secret_key = os.getenv('SECRET_KEY')

TWILIO_ACCOUNT = os.getenv('TWILIO_ACCOUNT')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
ADMIN_WHATSAPP = os.getenv('ADMIN_WHATSAPP')
TWILIO_WHATSAPP_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER')


db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Rotas administrativas (para adicionar produtos)
UPLOAD_FOLDER = 'static/imagens'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Limite de 16MB


def enviar_whatsapp_admin(usuario, itens, total, pedido_id):
    """
    Envia notificação de nova compra para o admin via WhatsApp
    Args:
        usuario: Objeto Usuario do cliente
        itens: Lista de itens do carrinho
        total: Valor total da compra
        pedido_id: ID do pedido
    """
    client = Client(TWILIO_ACCOUNT, TWILIO_AUTH_TOKEN)
    
    # Formatar itens
    itens_formatados = "\n".join(
        f"➡ {item.produto.nome} ({item.quantidade}x): R${item.produto.preco * item.quantidade:.2f}"
        for item in itens
    )
    
    # Criar mensagem com dados do cliente
    mensagem = f"""
    🛍️ *NOVA COMPRA NO SITE* 🛍️

    👤 *Cliente:* {usuario.nome}
    📧 *Email:* {usuario.email}
    📞 *Telefone:* {usuario.telefone or 'Não informado'}

    🆔 *Pedido:* #{pedido_id}
    
    🛒 *Itens:*
    {itens_formatados}

    💰 *Total:* R${total:.2f}

    ⏱️ *Data/Hora:* {datetime.now().strftime('%d/%m/%Y %H:%M')}
    """
    
    try:
        message = client.messages.create(
            body=mensagem,
            from_=TWILIO_WHATSAPP_NUMBER,
            to=ADMIN_WHATSAPP
        )
        print(f"✅ Notificação enviada! SID: {message.sid}")
        return True
    except Exception as e:
        print(f"❌ Erro ao enviar WhatsApp: {str(e)}")
        return False

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha_hash = db.Column(db.String(256), nullable=False)
    telefone = db.Column(db.String(20))
    admin = db.Column(db.Boolean, default=False)
    
    # Relacionamento com carrinho (opcional)
    carrinhos = db.relationship('Carrinho', backref='usuario', lazy=True)
    
    def set_senha(self, senha):
    # Use pbkdf2 como método mais compacto (ainda seguro)
        self.senha_hash = generate_password_hash(
        senha,
        method='pbkdf2:sha256',
        salt_length=8
    )
    def check_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)

# Modelo de Produto (Frutas)
class Produto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    preco = db.Column(db.Float, nullable=False)
    descricao = db.Column(db.Text)
    imagem = db.Column(db.String(100))
    estoque = db.Column(db.Integer, default=0)

# Modelo de Carrinho de Compras
class Carrinho(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'))
    quantidade = db.Column(db.Integer, default=1)
    produto = db.relationship('Produto', backref='carrinhos')
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))

# Rotas do site
@app.route('/')
def index():
    # Aumente o número de itens se necessário
    destaques = Produto.query.all()
    return render_template('index.html', destaques=destaques)

@app.route('/produto/<int:id>')
def produto(id):
    produto = Produto.query.get_or_404(id)
    return render_template('produto.html', produto=produto)

@app.route('/adicionar_carrinho/<int:produto_id>', methods=['POST'])
def adicionar_carrinho(produto_id):
    # Verifica se o usuário está logado
    if 'usuario_id' not in session:
        flash('Por favor, faça login para adicionar itens ao carrinho', 'warning')
        return redirect(url_for('login'))

    try:
        # Obtém o produto e verifica se existe
        produto = Produto.query.get_or_404(produto_id)
        
        # Obtém a quantidade do formulário (padrão para 1 se não especificado)
        quantidade = int(request.form.get('quantidade', 1))
        
        # Verifica se há estoque suficiente
        if quantidade <= 0:
            flash('Quantidade inválida', 'error')
            return redirect(url_for('produto', id=produto_id))
            
        if produto.estoque < quantidade:
            flash(f'Quantidade indisponível. Estoque atual: {produto.estoque}', 'error')
            return redirect(url_for('produto', id=produto_id))

        # Verifica se o item já está no carrinho
        item_carrinho = Carrinho.query.filter_by(
            usuario_id=session['usuario_id'], 
            produto_id=produto_id
        ).first()

        if item_carrinho:
            # Verifica se a nova quantidade + a atual não excede o estoque
            nova_quantidade = item_carrinho.quantidade + quantidade
            if produto.estoque < nova_quantidade:
                flash(
                    f'Você já tem {item_carrinho.quantidade} no carrinho. ' +
                    f'Estoque insuficiente para adicionar mais {quantidade}.',
                    'error'
                )
                return redirect(url_for('produto', id=produto_id))
                
            item_carrinho.quantidade = nova_quantidade
        else:
            # Adiciona novo item ao carrinho
            item_carrinho = Carrinho(
                usuario_id=session['usuario_id'],
                produto_id=produto_id,
                quantidade=quantidade
            )
            db.session.add(item_carrinho)

        db.session.commit()
        flash(f'{quantidade} {produto.nome}(s) adicionado(s) ao carrinho!', 'success')

    except Exception as e:
        db.session.rollback()
        print(f"Erro ao adicionar ao carrinho: {str(e)}")
        flash('Ocorreu um erro ao adicionar o item ao carrinho', 'error')

    # Redireciona de volta para a página do produto ou para a origem
    return redirect(request.referrer or url_for('produto', id=produto_id))

@app.route('/carrinho')
def carrinho():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    
    itens = Carrinho.query.filter_by(usuario_id=session['usuario_id']).all()
    total = sum(item.produto.preco * item.quantidade for item in itens)
    return render_template('carrinho.html', itens=itens, total=total)

@app.route('/remover_item/<int:item_id>')
def remover_item(item_id):
    item = Carrinho.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('carrinho'))


@app.route('/finalizar_compra')
def finalizar_compra():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    # Obter dados do usuário
    usuario = Usuario.query.get(session['usuario_id'])
    
    # Obter itens do carrinho
    itens = Carrinho.query.filter_by(usuario_id=usuario.id).all()
    total = sum(item.produto.preco * item.quantidade for item in itens)
    pedido_id = f"PED{db.session.query(db.func.max(Carrinho.id)).scalar() + 1:04d}"
    
    # Enviar notificação
    enviar_whatsapp_admin(
        usuario=usuario,
        itens=itens,
        total=total,
        pedido_id=pedido_id
    )

    # Limpar carrinho
    Carrinho.query.filter_by(usuario_id=session['usuario_id']).delete()
    db.session.commit()

    flash('Compra finalizada! O admin foi notificado.', 'success')
    return render_template('compra_finalizada.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            email = request.form.get('email')
            senha = request.form.get('senha')
            
            if not email or not senha:
                flash('Preencha todos os campos', 'danger')
                return redirect(url_for('login'))

            usuario = Usuario.query.filter_by(email=email).first()
            
            if not usuario:
                flash('Credenciais inválidas', 'danger')
                return redirect(url_for('login'))
                
            if not usuario.check_senha(senha):
                flash('Credenciais inválidas', 'danger')
                return redirect(url_for('login'))
            
            # Login bem-sucedido
            session['usuario_id'] = usuario.id
            session['usuario_nome'] = usuario.nome
            session['admin'] = usuario.admin
            
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('index'))
            
        except Exception as e:
            app.logger.error(f'Erro no login: {str(e)}')
            flash('Ocorreu um erro durante o login', 'danger')
    
    return render_template('login.html')

@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if request.method == 'POST':
        try:
            data = {
                'nome': request.form.get('nome'),
                'email': request.form.get('email'),
                'telefone': request.form.get('telefone'),
                'admin': False
            }
            
            if Usuario.query.filter_by(email=data['email']).first():
                flash('Email já cadastrado', 'error')
                return redirect(url_for('cadastro'))
            
            usuario = Usuario(**data)
            usuario.set_senha(request.form.get('senha'))  # Garanta que este método existe
            
            db.session.add(usuario)
            db.session.commit()
            
            flash('Cadastro realizado!', 'success')
            return redirect(url_for('login'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erro: {str(e)}', 'error')
            return redirect(url_for('cadastro'))
    print(Usuario.query.all()) 
    
    return render_template('cadastro.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Você foi deslogado', 'info')
    return redirect(url_for('index'))

@app.route('/admin/adicionar_produto', methods=['GET', 'POST'])
def adicionar_produto():
    if request.method == 'POST':
        try:
            # Validação dos campos do formulário
            nome = request.form['nome']
            if not nome:
                raise ValueError("O nome do produto é obrigatório")
                
            preco = float(request.form['preco'])
            if preco <= 0:
                raise ValueError("O preço deve ser maior que zero")
                
            estoque = int(request.form['estoque'])
            if estoque < 0:
                raise ValueError("O estoque não pode ser negativo")
                
            descricao = request.form['descricao']
            
            # Processamento da imagem
            if 'imagem' not in request.files:
                raise ValueError("Nenhum arquivo de imagem enviado")
                
            imagem = request.files['imagem']
            
            # Se o usuário não selecionar arquivo, o navegador pode
            # enviar um arquivo vazio sem nome
            if imagem.filename == '':
                raise ValueError("Nenhuma imagem selecionada")
                
            if imagem and allowed_file(imagem.filename):
                # Garante um nome de arquivo seguro
                filename = secure_filename(imagem.filename)
                
                # Cria um nome único para evitar sobrescrita
                unique_filename = f"{os.urandom(8).hex()}_{filename}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                
                # Garante que o diretório existe
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                
                # Salva o arquivo
                imagem.save(save_path)
                
                # Criação do produto no banco de dados
                novo_produto = Produto(
                    nome=nome,
                    preco=preco,
                    descricao=descricao,
                    imagem=unique_filename,
                    estoque=estoque
                )
                
                db.session.add(novo_produto)
                db.session.commit()
                
                flash('Produto adicionado com sucesso!', 'success')
                return redirect(url_for('index'))
            else:
                raise ValueError("Tipo de arquivo não permitido. Use apenas PNG, JPG ou GIF")
                
        except ValueError as e:
            flash(str(e), 'error')
        except Exception as e:
            flash('Ocorreu um erro ao adicionar o produto', 'error')
            print(f"Erro: {str(e)}")
    
    return render_template('adicionar_produto.html')

@app.route('/admin/editar_produto/<int:id>', methods=['GET', 'POST'])
def editar_produto(id):
    produto = Produto.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # Validação básica
            produto.nome = request.form['nome']
            if not produto.nome:
                raise ValueError("O nome do produto é obrigatório")
                
            produto.preco = float(request.form['preco'])
            if produto.preco <= 0:
                raise ValueError("O preço deve ser maior que zero")
                
            produto.estoque = int(request.form['estoque'])
            if produto.estoque < 0:
                raise ValueError("O estoque não pode ser negativo")
                
            produto.descricao = request.form['descricao']
            
            # Processamento da imagem (se uma nova foi enviada)
            if 'imagem' in request.files:
                imagem = request.files['imagem']
                if imagem and allowed_file(imagem.filename):
                    # Remove a imagem antiga se não for a default
                    if produto.imagem != 'default.jpg':
                        try:
                            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], produto.imagem))
                        except:
                            pass
                    
                    # Salva a nova imagem
                    filename = secure_filename(imagem.filename)
                    imagem.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    produto.imagem = filename
            
            db.session.commit()
            
            flash('Produto atualizado com sucesso!', 'success')
            return redirect(url_for('produto', id=produto.id))
            
        except ValueError as e:
            flash(str(e), 'error')
        except Exception as e:
            flash('Ocorreu um erro ao editar o produto', 'error')
            print(f"Erro: {str(e)}")
    
    return render_template('editar_produto.html', produto=produto)

@app.route('/admin/excluir_produto/<int:id>', methods=['POST'])
def excluir_produto(id):
    if 'usuario_id' not in session or session['usuario_id'] != 1:
        return redirect(url_for('index'))
    
    produto = Produto.query.get_or_404(id)
    
    try:
        # Remove a imagem associada se não for a default
        if produto.imagem != 'default.jpg':
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], produto.imagem))
            except:
                pass
        
        db.session.delete(produto)
        db.session.commit()
        flash('Produto excluído com sucesso!', 'success')
    except Exception as e:
        flash('Ocorreu um erro ao excluir o produto', 'error')
        print(f"Erro: {str(e)}")
    
    return redirect(url_for('index'))

@app.route('/debug-usuario')
def debug_usuario():
    try:
        # Testa consulta
        usuarios = Usuario.query.all()
        # Testa inserção (remove depois)
        novo = Usuario(
            nome="Teste",
            email="teste@teste.com",
            senha_hash="teste123",
            telefone="11999999999"
        )
        db.session.add(novo)
        db.session.commit()
        return "Operações com usuario OK!"
    except Exception as e:
        return f"Erro: {str(e)}", 500

@app.route('/debug-login')
def debug_login():
    try:
        # Testa um usuário existente
        usuario = Usuario.query.first()
        if usuario:
            return f"Usuário teste: {usuario.email} - Senha válida: {usuario.check_senha('senha_test')}"
        return "Nenhum usuário cadastrado"
    except Exception as e:
        return f"Erro: {str(e)}", 500

@app.before_request
def before_request():
    if 'usuario_id' not in session and request.endpoint not in ['login', 'cadastro', 'static']:
        return redirect(url_for('login'))

def create_app():
    return app

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
