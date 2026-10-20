import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import random
import string
import io
from PIL import Image, ImageDraw, ImageFont

# Linux sunucularında grafik çizerken çökme yapmaması için arkaplan motoru:
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from flask import Flask
from threading import Thread

# --- MINIK WEB SUNUCUSU (UptimeRobot İçin 7/24 Aktif Tutucu) ---
app = Flask('')

@app.route('/')
def home():
    return "Merkez Bankası Botu 7/24 Aktif!"

def run():
    # Render.com'un atadığı portu veya varsayılan 8080'i kullanır
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- AYARLAR VE VERİTABANI ---
TOKEN = os.getenv("DISCORD_TOKEN")
DB_FILE = "bank_db.json"

def load_db():
    if not os.path.exists(DB_FILE):
        return {"users": {}, "kasa": 0, "bekleyen_talepler": {}}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def generate_iban():
    return "TR" + "".join([str(random.randint(0, 9)) for _ in range(24)])

def generate_card_number():
    return "4444 " + " ".join(["".join([str(random.randint(0, 9)) for _ in range(4)]) for _ in range(3)])

def generate_req_id():
    return "REQ-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

# --- GÖRSEL KREDİ KARTI ÜRETİCİ (PILLOW) ---
def generate_credit_card(user_name, card_number, exp_date, cvv):
    img = Image.new('RGB', (800, 500), color='#1e1e2f')
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, 800, 15], fill='#d4af37')
    draw.rectangle([0, 485, 800, 500], fill='#d4af37')
    draw.rectangle([80, 150, 160, 210], fill='#e0a96d', outline='#b8860b', width=2)
    draw.line([80, 180, 160, 180], fill='#b8860b', width=2)

    try:
        font_large = ImageFont.truetype("arial.ttf", 36)
        font_small = ImageFont.truetype("arial.ttf", 22)
    except:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    draw.text((80, 50), "MERKEZ BANKASI", fill="#ffffff", font=font_large)
    draw.text((80, 260), card_number, fill="#ffffff", font=font_large)
    draw.text((80, 340), f"SKT: {exp_date}", fill="#aaaaaa", font=font_small)
    draw.text((320, 340), f"CVV: {cvv}", fill="#aaaaaa", font=font_small)
    draw.text((80, 400), user_name.upper(), fill="#ffffff", font=font_large)

    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer

# --- TIKLANABİLİR BUTONLU ONAY SİSTEMİ ---
class TalepOnayView(discord.ui.View):
    def __init__(self, req_id):
        super().__init__(timeout=None)
        self.req_id = req_id

    @discord.ui.button(label="Onayla", style=discord.ButtonStyle.green, custom_id="onay_btn")
    async def onayla(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Sadece yöneticiler onay verebilir!", ephemeral=True)
        
        db = load_db()
        if self.req_id not in db["bekleyen_talepler"]:
            return await interaction.response.send_message("❌ İşlem zaten tamamlanmış.", ephemeral=True)

        talep = db["bekleyen_talepler"][self.req_id]
        user_id = talep["user_id"]

        if talep["tur"] == "satin_alim":
            db["kasa"] += talep["toplam"]
        elif talep["tur"] == "kredi":
            db["users"][user_id]["bakiye"] += talep["tutar"]
            db["users"][user_id]["kredi_borcu"] += talep["tutar"]

        del db["bekleyen_talepler"][self.req_id]
        save_db(db)

        for child in self.children:
            child.disabled = True
        
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = "✅ İşlem Onaylandı"
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Reddet", style=discord.ButtonStyle.red, custom_id="red_btn")
    async def reddet(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Sadece yöneticiler reddedebilir!", ephemeral=True)

        db = load_db()
        if self.req_id not in db["bekleyen_talepler"]:
            return await interaction.response.send_message("❌ İşlem zaten tamamlanmış.", ephemeral=True)

        talep = db["bekleyen_talepler"][self.req_id]
        user_id = talep["user_id"]

        if talep["tur"] == "satin_alim":
            db["users"][user_id]["bakiye"] += talep["toplam"]

        del db["bekleyen_talepler"][self.req_id]
        save_db(db)

        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "⛔ İşlem Reddedildi"
        await interaction.response.edit_message(embed=embed, view=self)

# --- BOT KURULUMU ---
class BankBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        faiz_isle.start() 

bot = BankBot()

# --- GÜNLÜK FAİZ ZAMANLAYICISI (24 SAATTE BİR %2) ---
@tasks.loop(hours=24)
async def faiz_isle():
    db = load_db()
    for user_id, user_data in db["users"].items():
        if user_data.get("kredi_borcu", 0) > 0:
            user_data["kredi_borcu"] *= 1.02
    save_db(db)

@bot.event
async def on_ready():
    print(f"{bot.user} aktif! Sistem 7/24 çalışmaya hazır.")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Borsa ve Kurları"))

# --- OTOMATİK HESAP VE KANAL AÇMA ---
@bot.event
async def on_member_join(member):
    db = load_db()
    user_id = str(member.id)
    
    if user_id not in db["users"]:
        db["users"][user_id] = {
            "bakiye": 0.0,
            "iban": generate_iban(),
            "kart_no": generate_card_number(),
            "skt": "12/28",
            "cvv": str(random.randint(100, 999)),
            "kredi_borcu": 0.0,
            "kredi_notu": 1000
        }
        save_db(db)

        guild = member.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        kanal_adi = f"💳・{member.name}-hesap"
        try:
            await guild.create_text_channel(kanal_adi, overwrites=overwrites)
        except Exception as e:
            pass

# --- KOMUTLAR ---
@bot.tree.command(name="help", description="Tüm banka komutlarını listeler.")
async def help_cmd(interaction: discord.Interaction):
    is_admin = interaction.user.guild_permissions.administrator
    embed = discord.Embed(title="🏦 Merkez Bankası Menüsü", color=discord.Color.blurple())
    
    user_cmds = """
    `/hesap-bilgi` - Bakiyeni ve hesap detaylarını gör.
    `/kartim` - Görsel banka kartını üretir ve atar.
    `/al-link` - Link ile komisyonlu satın alım talebi oluşturur.
    `/kredi-cek` - Bankadan kredi talep et.
    """
    embed.add_field(name="👤 Müşteri Komutları", value=user_cmds, inline=False)
    
    if is_admin:
        admin_cmds = """
        `/kasa-grafik` - Kasadaki paranı ve varlık dağılım grafiğini çizer.
        """
        embed.add_field(name="🛠️ Yönetici Komutları", value=admin_cmds, inline=False)
        
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="hesap-bilgi", description="Banka hesabının güncel durumunu gösterir.")
async def hesap_bilgi(interaction: discord.Interaction):
    db = load_db()
    user_id = str(interaction.user.id)
    
    if user_id not in db["users"]:
        return await interaction.response.send_message("❌ Bankamızda hesabınız bulunmamaktadır.", ephemeral=True)
    
    hesap = db["users"][user_id]
    embed = discord.Embed(title="🏦 Merkez Bankası Hesap Özeti", color=discord.Color.gold())
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    embed.add_field(name="💰 Güncel Bakiye", value=f"**{hesap['bakiye']:,.2f} ₺**", inline=False)
    embed.add_field(name="🏛️ IBAN", value=f"`{hesap['iban']}`", inline=False)
    embed.add_field(name="📈 Kredi Notu", value=f"{hesap['kredi_notu']}", inline=True)
    embed.add_field(name="📉 Kredi Borcu", value=f"{hesap['kredi_borcu']:,.2f} ₺", inline=True)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="kartim", description="Sana özel dijital kredi kartını üretir.")
async def kartim(interaction: discord.Interaction):
    db = load_db()
    user_id = str(interaction.user.id)
    
    if user_id not in db["users"]:
        return await interaction.response.send_message("❌ Hesabınız bulunamadı.", ephemeral=True)
        
    hesap = db["users"][user_id]
    
    card_img = generate_credit_card(
        user_name=interaction.user.display_name,
        card_number=hesap.get("kart_no", generate_card_number()),
        exp_date=hesap.get("skt", "12/28"),
        cvv=hesap.get("cvv", "123")
    )
    
    file = discord.File(card_img, filename="kredi_karti.png")
    embed = discord.Embed(title="💳 Dijital Kredi Kartınız", color=discord.Color.dark_purple())
    embed.set_image(url="attachment://kredi_karti.png")
    
    await interaction.response.send_message(embed=embed, file=file)

@bot.tree.command(name="al-link", description="Link üzerinden komisyonlu satın alım talebi oluşturur.")
async def al_link(interaction: discord.Interaction, link: str, fiyat: float):
    db = load_db()
    user_id = str(interaction.user.id)
    
    if user_id not in db["users"]:
        return await interaction.response.send_message("❌ Hesabınız bulunamadı.", ephemeral=True)
    
    komisyon_orani = 0.60
    kesilecek_komisyon = fiyat * komisyon_orani
    toplam_tutar = fiyat + kesilecek_komisyon
    
    if db["users"][user_id]["bakiye"] < toplam_tutar:
        embed = discord.Embed(title="❌ Yetersiz Bakiye", description=f"Toplam **{toplam_tutar:,.2f} ₺** gerekiyor.", color=discord.Color.red())
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    db["users"][user_id]["bakiye"] -= toplam_tutar
    req_id = generate_req_id()
    
    db["bekleyen_talepler"][req_id] = {
        "tur": "satin_alim",
        "user_id": user_id,
        "tutar": fiyat,
        "komisyon": kesilecek_komisyon,
        "toplam": toplam_tutar,
        "link": link
    }
    save_db(db)
    
    embed = discord.Embed(title="⏳ İşlem Askıya Alındı", color=discord.Color.orange())
    embed.description = f"Satın alım tutarı düşüldü, **Yönetici Onayı** bekleniyor."
    embed.add_field(name="Tutar", value=f"{fiyat:,.2f} ₺")
    embed.add_field(name="Vergi (%60)", value=f"{kesilecek_komisyon:,.2f} ₺")
    embed.add_field(name="İşlem Kodu", value=f"`{req_id}`")
    
    view = TalepOnayView(req_id)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="kredi-cek", description="Banka kasasından kredi talep et.")
async def kredi_cek(interaction: discord.Interaction, tutar: float):
    db = load_db()
    user_id = str(interaction.user.id)
    
    if user_id not in db["users"]:
        return await interaction.response.send_message("❌ Hesabınız bulunamadı.", ephemeral=True)
    
    req_id = generate_req_id()
    db["bekleyen_talepler"][req_id] = {
        "tur": "kredi",
        "user_id": user_id,
        "tutar": tutar
    }
    save_db(db)
    
    embed = discord.Embed(title="📑 Kredi Talebi Alındı", color=discord.Color.blue())
    embed.description = f"**{tutar:,.2f} ₺** kredi talebi oluşturuldu."
    embed.add_field(name="İşlem Kodu", value=f"`{req_id}`")
    
    view = TalepOnayView(req_id)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="kasa-grafik", description="[YÖNETİCİ] Banka kasasının dağılım grafiğini çizer.")
@app_commands.default_permissions(administrator=True)
async def kasa_grafik(interaction: discord.Interaction):
    db = load_db()
    
    toplam_kasa = db.get("kasa", 0)
    toplam_kredi = sum(u.get("kredi_borcu", 0) for u in db["users"].values())
    toplam_mevduat = sum(u.get("bakiye", 0) for u in db["users"].values())

    labels = ['Banka Kasası', 'Dağıtılan Krediler', 'Müşteri Bakiyeleri']
    sizes = [toplam_kasa, toplam_kredi, toplam_mevduat]
    colors = ['#2ecc71', '#e74c3c', '#3498db']

    if sum(sizes) == 0:
        sizes = [1, 1, 1]

    plt.figure(figsize=(6, 6))
    plt.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=140)
    plt.title('Merkez Bankası Varlık Dağılımı')

    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight')
    buffer.seek(0)
    plt.close()

    file = discord.File(buffer, filename="kasa_grafik.png")
    embed = discord.Embed(title="📊 Banka Finansal Durum Grafiği", color=discord.Color.gold())
    embed.set_image(url="attachment://kasa_grafik.png")
    
    await interaction.response.send_message(embed=embed, file=file)

# Flask sunucusunu başlatıp ardından botu çalıştırıyoruz
if TOKEN:
    keep_alive()
    bot.run(TOKEN)
else:
    print("❌ DISCORD_TOKEN bulunamadı! Lütfen Environment Variables bölümüne ekleyin.")
