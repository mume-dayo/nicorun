
import discord
from discord.ext import commands
import json
import os
from datetime import datetime
from flask import Flask
from threading import Thread
import time

# Flask app for Render health check
app = Flask(__name__)

@app.route('/')
def home():
    return "Discord Bot is running!"

@app.route('/health')
def health():
    return {"status": "healthy", "bot": "running"}

def run_flask():
    """Run Flask server"""
    app.run(host='0.0.0.0', port=5000)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='/', intents=intents)

# Data storage files
DATA_FILE = 'bot_data.json'

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'users': {},
        'vending_machines': {},
        'transactions': [],
        'tickets': {}
    }

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'Failed to sync commands: {e}')

# Authentication command
@bot.tree.command(name='auth', description='認証してロールを取得')
async def auth(interaction: discord.Interaction):
    data = load_data()
    user_id = str(interaction.user.id)
    
    # Add user to database if not exists
    if user_id not in data['users']:
        data['users'][user_id] = {
            'coins': 100,
            'authenticated': True,
            'join_date': datetime.now().isoformat()
        }
    else:
        data['users'][user_id]['authenticated'] = True
    
    save_data(data)
    
    # Try to add role (you'll need to create a role named "認証済み" in your server)
    try:
        role = discord.utils.get(interaction.guild.roles, name="認証済み")
        if role:
            await interaction.user.add_roles(role)
            await interaction.response.send_message('✅ 認証が完了しました！ロールが付与されました。', ephemeral=True)
        else:
            await interaction.response.send_message('✅ 認証が完了しました！（ロールが見つかりませんでした）', ephemeral=True)
    except Exception as e:
        await interaction.response.send_message('✅ 認証が完了しましたが、ロールの付与に失敗しました。', ephemeral=True)

# Vending Machine View with buttons
class VendingMachineView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.setup_buttons()
    
    def setup_buttons(self):
        data = load_data()
        if self.guild_id in data['vending_machines']:
            items = data['vending_machines'][self.guild_id]['items']
            for item_id, item in list(items.items())[:25]:  # Discord limit of 25 buttons
                button = discord.ui.Button(
                    label=f"{item['name']} ({item['price']}コイン)",
                    style=discord.ButtonStyle.primary if item['stock'] > 0 else discord.ButtonStyle.secondary,
                    custom_id=f"buy_{item_id}",
                    disabled=item['stock'] <= 0
                )
                button.callback = self.create_buy_callback(item_id)
                self.add_item(button)
    
    def create_buy_callback(self, item_id):
        async def buy_callback(interaction):
            await self.buy_item(interaction, item_id)
        return buy_callback
    
    async def buy_item(self, interaction, item_id):
        data = load_data()
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        
        # Check if user exists
        if user_id not in data['users']:
            await interaction.response.send_message('❌ 先に /auth で認証してください。', ephemeral=True)
            return
        
        # Check if item exists
        if guild_id not in data['vending_machines'] or item_id not in data['vending_machines'][guild_id]['items']:
            await interaction.response.send_message('❌ アイテムが見つかりません。', ephemeral=True)
            return
        
        item = data['vending_machines'][guild_id]['items'][item_id]
        user = data['users'][user_id]
        
        # Check stock
        if item['stock'] <= 0:
            await interaction.response.send_message('❌ 在庫がありません。', ephemeral=True)
            return
        
        # Check coins
        if user['coins'] < item['price']:
            await interaction.response.send_message(f'❌ コインが不足しています。必要: {item["price"]}、所持: {user["coins"]}', ephemeral=True)
            return
        
        # Process purchase
        user['coins'] -= item['price']
        item['stock'] -= 1
        
        # Record transaction
        transaction = {
            'user_id': user_id,
            'item_name': item['name'],
            'price': item['price'],
            'timestamp': datetime.now().isoformat(),
            'guild_id': guild_id
        }
        data['transactions'].append(transaction)
        
        save_data(data)
        
        # Update the view with new button states
        new_view = VendingMachineView(guild_id)
        
        # Create updated embed
        vending_machine = data['vending_machines'][guild_id]
        embed = discord.Embed(title='🏪 自動販売機', color=0x00ff00)
        
        if not vending_machine['items']:
            embed.description = '商品がありません。'
        else:
            for item_id_display, item_display in vending_machine['items'].items():
                embed.add_field(
                    name=f"{item_display['name']} - {item_display['price']}コイン",
                    value=f"在庫: {item_display['stock']}個\nID: {item_id_display}",
                    inline=True
                )
        
        await interaction.response.edit_message(embed=embed, view=new_view)
        await interaction.followup.send(f'✅ {item["name"]} を購入しました！残りコイン: {user["coins"]}', ephemeral=True)

# Show vending machine
@bot.tree.command(name='show', description='自動販売機を表示')
async def show_vending_machine(interaction: discord.Interaction):
    data = load_data()
    guild_id = str(interaction.guild.id)
    
    if guild_id not in data['vending_machines']:
        data['vending_machines'][guild_id] = {
            'items': {},
            'created_at': datetime.now().isoformat()
        }
        save_data(data)
    
    vending_machine = data['vending_machines'][guild_id]
    
    if not vending_machine['items']:
        embed = discord.Embed(title='🏪 自動販売機', description='商品がありません。', color=0x00ff00)
        await interaction.response.send_message(embed=embed)
    else:
        embed = discord.Embed(title='🏪 自動販売機', color=0x00ff00)
        for item_id, item in vending_machine['items'].items():
            embed.add_field(
                name=f"{item['name']} - {item['price']}コイン",
                value=f"在庫: {item['stock']}個\nID: {item_id}",
                inline=True
            )
        
        view = VendingMachineView(guild_id)
        await interaction.response.send_message(embed=embed, view=view)

# Add new item to vending machine
@bot.tree.command(name='newitem', description='自動販売機に新しいアイテムを追加')
async def new_item(interaction: discord.Interaction, name: str, price: int, stock: int = 1):
    data = load_data()
    guild_id = str(interaction.guild.id)
    
    if guild_id not in data['vending_machines']:
        data['vending_machines'][guild_id] = {'items': {}}
    
    item_id = str(len(data['vending_machines'][guild_id]['items']) + 1)
    data['vending_machines'][guild_id]['items'][item_id] = {
        'name': name,
        'price': price,
        'stock': stock,
        'created_by': str(interaction.user.id)
    }
    
    save_data(data)
    await interaction.response.send_message(f'✅ アイテム "{name}" を追加しました！（ID: {item_id}）')

# Add coins to user
@bot.tree.command(name='addcoins', description='ユーザーにコインを追加')
async def add_coins(interaction: discord.Interaction, user: discord.Member, amount: int):
    data = load_data()
    user_id = str(user.id)
    
    if user_id not in data['users']:
        data['users'][user_id] = {'coins': 0, 'authenticated': False}
    
    data['users'][user_id]['coins'] += amount
    save_data(data)
    
    await interaction.response.send_message(f'✅ {user.display_name} に {amount} コインを追加しました！')

# Delete item from vending machine
@bot.tree.command(name='del', description='自動販売機からアイテムを削除')
async def delete_item(interaction: discord.Interaction, item_id: str):
    data = load_data()
    guild_id = str(interaction.guild.id)
    
    if guild_id in data['vending_machines'] and item_id in data['vending_machines'][guild_id]['items']:
        item_name = data['vending_machines'][guild_id]['items'][item_id]['name']
        del data['vending_machines'][guild_id]['items'][item_id]
        save_data(data)
        await interaction.response.send_message(f'✅ アイテム "{item_name}" を削除しました！')
    else:
        await interaction.response.send_message('❌ アイテムが見つかりません。')

# Change item price
@bot.tree.command(name='change', description='アイテムの価格を変更')
async def change_price(interaction: discord.Interaction, item_id: str, new_price: int):
    data = load_data()
    guild_id = str(interaction.guild.id)
    
    if guild_id in data['vending_machines'] and item_id in data['vending_machines'][guild_id]['items']:
        old_price = data['vending_machines'][guild_id]['items'][item_id]['price']
        data['vending_machines'][guild_id]['items'][item_id]['price'] = new_price
        save_data(data)
        await interaction.response.send_message(f'✅ 価格を {old_price} → {new_price} コインに変更しました！')
    else:
        await interaction.response.send_message('❌ アイテムが見つかりません。')

# Add stock to item
@bot.tree.command(name='additem', description='アイテムの在庫を追加')
async def add_stock(interaction: discord.Interaction, item_id: str, amount: int):
    data = load_data()
    guild_id = str(interaction.guild.id)
    
    if guild_id in data['vending_machines'] and item_id in data['vending_machines'][guild_id]['items']:
        data['vending_machines'][guild_id]['items'][item_id]['stock'] += amount
        save_data(data)
        await interaction.response.send_message(f'✅ 在庫を {amount} 個追加しました！')
    else:
        await interaction.response.send_message('❌ アイテムが見つかりません。')

# Buy item from vending machine
@bot.tree.command(name='buy', description='自動販売機からアイテムを購入')
async def buy_item(interaction: discord.Interaction, item_id: str):
    data = load_data()
    guild_id = str(interaction.guild.id)
    user_id = str(interaction.user.id)
    
    # Check if user exists
    if user_id not in data['users']:
        await interaction.response.send_message('❌ 先に /auth で認証してください。')
        return
    
    # Check if item exists
    if guild_id not in data['vending_machines'] or item_id not in data['vending_machines'][guild_id]['items']:
        await interaction.response.send_message('❌ アイテムが見つかりません。')
        return
    
    item = data['vending_machines'][guild_id]['items'][item_id]
    user = data['users'][user_id]
    
    # Check stock
    if item['stock'] <= 0:
        await interaction.response.send_message('❌ 在庫がありません。')
        return
    
    # Check coins
    if user['coins'] < item['price']:
        await interaction.response.send_message(f'❌ コインが不足しています。必要: {item["price"]}、所持: {user["coins"]}')
        return
    
    # Process purchase
    user['coins'] -= item['price']
    item['stock'] -= 1
    
    # Record transaction
    transaction = {
        'user_id': user_id,
        'item_name': item['name'],
        'price': item['price'],
        'timestamp': datetime.now().isoformat(),
        'guild_id': guild_id
    }
    data['transactions'].append(transaction)
    
    save_data(data)
    
    await interaction.response.send_message(f'✅ {item["name"]} を購入しました！残りコイン: {user["coins"]}')

# View transactions
@bot.tree.command(name='transaction', description='取引履歴を表示')
async def view_transactions(interaction: discord.Interaction):
    data = load_data()
    user_id = str(interaction.user.id)
    
    user_transactions = [t for t in data['transactions'] if t['user_id'] == user_id]
    
    if not user_transactions:
        await interaction.response.send_message('取引履歴がありません。')
        return
    
    embed = discord.Embed(title='📊 取引履歴', color=0x0099ff)
    
    for i, transaction in enumerate(user_transactions[-10:]):  # Show last 10 transactions
        embed.add_field(
            name=f"{i+1}. {transaction['item_name']}",
            value=f"価格: {transaction['price']}コイン\n日時: {transaction['timestamp'][:10]}",
            inline=True
        )
    
    await interaction.response.send_message(embed=embed)

# Ticket system
@bot.tree.command(name='ticket', description='サポートチケットを作成')
async def create_ticket(interaction: discord.Interaction, subject: str, description: str = ""):
    data = load_data()
    user_id = str(interaction.user.id)
    ticket_id = str(len(data['tickets']) + 1)
    
    # Create ticket channel
    guild = interaction.guild
    category = discord.utils.get(guild.categories, name="🎫 チケット")
    
    # Create category if it doesn't exist
    if not category:
        category = await guild.create_category("🎫 チケット")
    
    # Set permissions for the ticket channel
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.owner: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    
    # Add permissions for users with Administrator permission
    for member in guild.members:
        if member.guild_permissions.administrator:
            overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    
    # Create the ticket channel
    channel_name = f"ticket-{ticket_id}-{interaction.user.name}"
    try:
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites
        )
        
        data['tickets'][ticket_id] = {
            'user_id': user_id,
            'subject': subject,
            'description': description,
            'status': 'open',
            'created_at': datetime.now().isoformat(),
            'guild_id': str(interaction.guild.id),
            'channel_id': str(ticket_channel.id)
        }
        
        save_data(data)
        
        # Send initial message to ticket channel
        embed = discord.Embed(
            title=f'🎫 チケット #{ticket_id}',
            description=f'**件名:** {subject}\n**説明:** {description or "なし"}\n**作成者:** {interaction.user.mention}',
            color=0xff9900
        )
        embed.add_field(name='ステータス', value='🟢 オープン', inline=True)
        embed.add_field(name='作成日時', value=f'<t:{int(datetime.now().timestamp())}:F>', inline=True)
        
        # Add close button
        view = TicketView(ticket_id)
        await ticket_channel.send(embed=embed, view=view)
        
        # Response to user
        await interaction.response.send_message(
            f'✅ チケット #{ticket_id} を作成しました！\n'
            f'専用チャンネル: {ticket_channel.mention}',
            ephemeral=True
        )
        
    except Exception as e:
        await interaction.response.send_message(f'❌ チケットチャンネルの作成に失敗しました: {str(e)}', ephemeral=True)

# Ticket View with close button
class TicketView(discord.ui.View):
    def __init__(self, ticket_id):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
    
    @discord.ui.button(label='チケットを閉じる', style=discord.ButtonStyle.danger, emoji='🔒')
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        
        if self.ticket_id not in data['tickets']:
            await interaction.response.send_message('❌ チケットが見つかりません。', ephemeral=True)
            return
        
        ticket = data['tickets'][self.ticket_id]
        user_id = str(interaction.user.id)
        
        # Check if user can close the ticket (creator or admin)
        if user_id != ticket['user_id'] and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ このチケットを閉じる権限がありません。', ephemeral=True)
            return
        
        # Update ticket status
        data['tickets'][self.ticket_id]['status'] = 'closed'
        data['tickets'][self.ticket_id]['closed_at'] = datetime.now().isoformat()
        data['tickets'][self.ticket_id]['closed_by'] = user_id
        save_data(data)
        
        # Update embed
        embed = discord.Embed(
            title=f'🎫 チケット #{self.ticket_id} (クローズ済み)',
            description=f'**件名:** {ticket["subject"]}\n**説明:** {ticket.get("description", "なし")}\n**作成者:** <@{ticket["user_id"]}>',
            color=0x808080
        )
        embed.add_field(name='ステータス', value='🔴 クローズ済み', inline=True)
        embed.add_field(name='クローズ日時', value=f'<t:{int(datetime.now().timestamp())}:F>', inline=True)
        embed.add_field(name='クローズ実行者', value=interaction.user.mention, inline=True)
        
        # Disable button
        button.disabled = True
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        # Send confirmation message
        await interaction.followup.send('🔒 チケットがクローズされました。')

# List tickets command
@bot.tree.command(name='tickets', description='チケット一覧を表示')
async def list_tickets(interaction: discord.Interaction):
    data = load_data()
    guild_id = str(interaction.guild.id)
    
    guild_tickets = {k: v for k, v in data['tickets'].items() if v['guild_id'] == guild_id}
    
    if not guild_tickets:
        await interaction.response.send_message('チケットがありません。', ephemeral=True)
        return
    
    embed = discord.Embed(title='🎫 チケット一覧', color=0x0099ff)
    
    for ticket_id, ticket in guild_tickets.items():
        status_emoji = '🟢' if ticket['status'] == 'open' else '🔴'
        creator = interaction.guild.get_member(int(ticket['user_id']))
        creator_name = creator.display_name if creator else 'Unknown User'
        
        embed.add_field(
            name=f"{status_emoji} チケット #{ticket_id}",
            value=f"**件名:** {ticket['subject']}\n**作成者:** {creator_name}\n**ステータス:** {ticket['status']}",
            inline=True
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Nuke channel
@bot.tree.command(name='nuke', description='チャンネルを再生成（設定を引き継ぎ）')
async def nuke_channel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message('❌ チャンネル管理権限が必要です。')
        return
    
    channel = interaction.channel
    
    # Store channel settings
    channel_name = channel.name
    channel_topic = channel.topic
    channel_category = channel.category
    channel_position = channel.position
    
    # Create new channel with same settings
    new_channel = await channel.guild.create_text_channel(
        name=channel_name,
        topic=channel_topic,
        category=channel_category,
        position=channel_position
    )
    
    # Delete old channel
    await channel.delete()
    
    # Send confirmation in new channel
    embed = discord.Embed(
        title='💥 チャンネルがヌークされました！',
        description='チャンネルが正常に再生成されました。',
        color=0xff0000
    )
    await new_channel.send(embed=embed)

# View user profile
@bot.tree.command(name='profile', description='ユーザープロフィールを表示')
async def view_profile(interaction: discord.Interaction, user: discord.Member = None):
    if user is None:
        user = interaction.user
    
    data = load_data()
    user_id = str(user.id)
    
    if user_id not in data['users']:
        await interaction.response.send_message('❌ ユーザーが見つかりません。')
        return
    
    user_data = data['users'][user_id]
    user_transactions = [t for t in data['transactions'] if t['user_id'] == user_id]
    
    embed = discord.Embed(
        title=f'👤 {user.display_name} のプロフィール',
        color=0x00ff00
    )
    embed.add_field(name='💰 コイン', value=str(user_data['coins']), inline=True)
    embed.add_field(name='🛒 購入回数', value=str(len(user_transactions)), inline=True)
    embed.add_field(name='✅ 認証状態', value='認証済み' if user_data.get('authenticated') else '未認証', inline=True)
    
    await interaction.response.send_message(embed=embed)

# Public Ticket Creation View
class PublicTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label='🎫 チケットを作成', style=discord.ButtonStyle.primary, emoji='🎫')
    async def create_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Show modal for ticket creation
        modal = TicketModal()
        await interaction.response.send_modal(modal)

# Ticket Creation Modal
class TicketModal(discord.ui.Modal, title='🎫 チケット作成'):
    def __init__(self):
        super().__init__()
    
    subject = discord.ui.TextInput(
        label='件名',
        placeholder='チケットの件名を入力してください...',
        required=True,
        max_length=100
    )
    
    description = discord.ui.TextInput(
        label='説明',
        placeholder='問題の詳細を入力してください...',
        style=discord.TextStyle.long,
        required=False,
        max_length=1000
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        user_id = str(interaction.user.id)
        ticket_id = str(len(data['tickets']) + 1)
        
        # Create ticket channel
        guild = interaction.guild
        category = discord.utils.get(guild.categories, name="🎫 チケット")
        
        # Create category if it doesn't exist
        if not category:
            category = await guild.create_category("🎫 チケット")
        
        # Set permissions for the ticket channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.owner: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        # Add permissions for users with Administrator permission
        for member in guild.members:
            if member.guild_permissions.administrator:
                overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        # Create the ticket channel
        channel_name = f"ticket-{ticket_id}-{interaction.user.name}"
        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites
            )
            
            data['tickets'][ticket_id] = {
                'user_id': user_id,
                'subject': str(self.subject.value),
                'description': str(self.description.value) if self.description.value else "",
                'status': 'open',
                'created_at': datetime.now().isoformat(),
                'guild_id': str(interaction.guild.id),
                'channel_id': str(ticket_channel.id)
            }
            
            save_data(data)
            
            # Send initial message to ticket channel
            embed = discord.Embed(
                title=f'🎫 チケット #{ticket_id}',
                description=f'**件名:** {self.subject.value}\n**説明:** {self.description.value or "なし"}\n**作成者:** {interaction.user.mention}',
                color=0xff9900
            )
            embed.add_field(name='ステータス', value='🟢 オープン', inline=True)
            embed.add_field(name='作成日時', value=f'<t:{int(datetime.now().timestamp())}:F>', inline=True)
            
            # Add close button
            view = TicketView(ticket_id)
            await ticket_channel.send(embed=embed, view=view)
            
            # Response to user
            await interaction.response.send_message(
                f'✅ チケット #{ticket_id} を作成しました！\n'
                f'専用チャンネル: {ticket_channel.mention}',
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.response.send_message(f'❌ チケットチャンネルの作成に失敗しました: {str(e)}', ephemeral=True)

# Ticket panel command
@bot.tree.command(name='ticket-panel', description='チケット作成パネルを設置')
async def ticket_panel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message('❌ チャンネル管理権限が必要です。', ephemeral=True)
        return
    
    embed = discord.Embed(
        title='🎫 サポートチケット',
        description='何かお困りのことがありましたら、下のボタンをクリックしてサポートチケットを作成してください。\n\n'
                   '**チケットについて:**\n'
                   '• 専用のプライベートチャンネルが作成されます\n'
                   '• あなたとサーバーの管理者のみがアクセス可能です\n'
                   '• 問題が解決したらチケットをクローズしてください',
        color=0x00ff99
    )
    embed.set_footer(text='24時間365日サポート対応')
    
    view = PublicTicketView()
    await interaction.response.send_message(embed=embed, view=view)

# Help system
COMMAND_HELP = {
    'auth': {
        'description': '認証してロールを取得',
        'usage': '/auth',
        'details': 'このコマンドを使用してボットに認証し、初期コイン(100枚)を受け取ります。また、"認証済み"ロールが付与されます。'
    },
    'show': {
        'description': '自動販売機を表示',
        'usage': '/show',
        'details': '現在の自動販売機の商品一覧をボタン付きで表示します。ボタンをクリックして商品を購入できます。'
    },
    'newitem': {
        'description': '自動販売機に新しいアイテムを追加',
        'usage': '/newitem <名前> <価格> [在庫数]',
        'details': '新しい商品を自動販売機に追加します。在庫数を省略した場合は1個になります。'
    },
    'addcoins': {
        'description': 'ユーザーにコインを追加',
        'usage': '/addcoins <ユーザー> <数量>',
        'details': '指定したユーザーにコインを追加します。管理者用コマンドです。'
    },
    'del': {
        'description': '自動販売機からアイテムを削除',
        'usage': '/del <アイテムID>',
        'details': '指定したIDの商品を自動販売機から完全に削除します。'
    },
    'change': {
        'description': 'アイテムの価格を変更',
        'usage': '/change <アイテムID> <新価格>',
        'details': '指定したアイテムの価格を変更します。'
    },
    'additem': {
        'description': 'アイテムの在庫を追加',
        'usage': '/additem <アイテムID> <数量>',
        'details': '指定したアイテムの在庫を追加します。'
    },
    'buy': {
        'description': '自動販売機からアイテムを購入',
        'usage': '/buy <アイテムID>',
        'details': '指定したIDの商品を購入します。十分なコインと在庫が必要です。'
    },
    'transaction': {
        'description': '取引履歴を表示',
        'usage': '/transaction',
        'details': 'あなたの購入履歴（最新10件）を表示します。'
    },
    'ticket': {
        'description': 'サポートチケットを作成',
        'usage': '/ticket <件名> [説明]',
        'details': 'サポートチケットを作成し、専用のプライベートチャンネルを生成します。オーナーと管理者のみがアクセス可能です。'
    },
    'tickets': {
        'description': 'チケット一覧を表示',
        'usage': '/tickets',
        'details': 'サーバー内の全チケットの一覧を表示します。管理者用コマンドです。'
    },
    'nuke': {
        'description': 'チャンネルを再生成（設定を引き継ぎ）',
        'usage': '/nuke',
        'details': '現在のチャンネルを削除し、同じ設定で再作成します。チャンネル管理権限が必要です。'
    },
    'profile': {
        'description': 'ユーザープロフィールを表示',
        'usage': '/profile [ユーザー]',
        'details': '指定したユーザー（省略時は自分）のプロフィール情報を表示します。'
    },
    'help': {
        'description': 'ヘルプを表示',
        'usage': '/help [コマンド名]',
        'details': 'コマンド一覧を表示します。コマンド名を指定すると詳細な説明を表示します。'
    },
    'ticket-panel': {
        'description': 'チケット作成パネルを設置',
        'usage': '/ticket-panel',
        'details': '誰でもボタンをクリックしてチケットを作成できるパネルを設置します。チャンネル管理権限が必要です。'
    }
}

@bot.tree.command(name='help', description='ヘルプを表示')
async def help_command(interaction: discord.Interaction, command: str = None):
    if command is None:
        # Show all commands
        embed = discord.Embed(
            title='🤖 ボットコマンド一覧',
            description='使用可能なコマンドの一覧です。詳細は `/help コマンド名` で確認できます。',
            color=0x0099ff
        )
        
        for cmd_name, cmd_info in COMMAND_HELP.items():
            embed.add_field(
                name=f"/{cmd_name}",
                value=cmd_info['description'],
                inline=False
            )
        
        embed.set_footer(text="例: /help auth - authコマンドの詳細を表示")
        await interaction.response.send_message(embed=embed)
    
    else:
        # Show specific command help
        if command in COMMAND_HELP:
            cmd_info = COMMAND_HELP[command]
            embed = discord.Embed(
                title=f'📖 /{command} コマンドヘルプ',
                color=0x00ff00
            )
            embed.add_field(name='説明', value=cmd_info['description'], inline=False)
            embed.add_field(name='使用方法', value=f"`{cmd_info['usage']}`", inline=False)
            embed.add_field(name='詳細', value=cmd_info['details'], inline=False)
            
            await interaction.response.send_message(embed=embed)
        else:
            available_commands = ', '.join(COMMAND_HELP.keys())
            await interaction.response.send_message(
                f'❌ コマンド "{command}" が見つかりません。\n'
                f'利用可能なコマンド: {available_commands}'
            )

def run_bot():
    """Run Discord bot"""
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print('DISCORD_TOKEN環境変数が設定されていません。')
        return
    
    print("Starting Discord bot...")
    bot.run(token)

# Run the application
if __name__ == '__main__':
    # Start Flask server in a separate thread
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    print("Flask server started on port 5000")
    
    # Start Discord bot
    run_bot()
