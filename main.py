import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import random
import string
import io
import math
from PIL import Image, ImageDraw, ImageFont

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from flask import Flask
from threading import Thread

# --- MINIK WEB SUNUCUSU (UptimeRobot İçin) ---
app = Flask('')

@app.route('/')
def home():
    return "Merkez Bankası Botu 7/24 Aktif!"

def run():
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
        return {
            "users": {}, 
            "kasa": 0, 
            "bekleyen_talepler": {},
            "ayarlar": {
                "komisyon_odeme": 0.60,
                "komisyon_cekme": 0.10,
                "komisyon_havale": 0.05,
                "havale_sinir": 100.0,
                "kredi_faiz": 0.05,
                "gecikme_cezasi": 50.0,
                "log_kanal_id": None
            }
        }
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
        if "ayarlar" not in db:
            db["ayarlar"] = {
                "komisyon_odeme": 0.60,
                "komisyon_cekme": 0.10,
                "komisyon_havale": 0.05,
                "havale_sinir": 100.0,
                "kredi_faiz": 0.05,
                "gecikme_cezasi": 50.0,
                "log_kanal_id": None
            }
        return db

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

async def auto_backup(bot):
    db = load_db()
    log_id = db["ayarlar"].get("log_kanal_id")
    if log_id:
        kanal = bot.get_channel(int(log_id))
        if kanal:
            try:
                file = discord.File(DB_FILE, filename="bank_db_yedek.json")
                await kanal.send("📂 **[OTOMATİK YEDEK]** Veritabanı Güncellendi:", file=file)
            except:
                pass

def generate_iban():
    return "TR" + "".join([str(random.randint(0, 9)) for _ in range(24)])

def generate_card_number():
    return "4444 " + " ".join(["".join([str(random.randint(0, 9)) for _ in range(4)]) for _ in range(3)])

def generate_req_id():
    return "REQ-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

def clean_iban(raw_iban: str) -> str:
    cleaned = raw_iban.strip().upper().replace(" ", "")
    if not cleaned.startswith("TR"):
        cleaned = "TR" + cleaned
    return cleaned

def clean_card_number(raw_card: str) -> str:
    digits = "".join(filter(str.isdigit, raw_card))
    return " ".join([digits[i:i+4] for i in range(0, len(digits), 4)])

def clean_skt(raw_skt: str) -> str:
    digits = "".join(filter(str.isdigit, raw_skt))
    if len(digits) == 4:
        return f"{digits[:2]}/{digits[2:]}"
    return raw_skt.strip()

def validate_positive_amount(val_str: str):
    try:
        val = float(val_str.replace(",", "."))
        if math.isnan(val) or math.isinf(val) or val <= 0: return None
        return round(val, 2)
    except ValueError:
        return None

def get_or_create_user(db, user_id):
    if user_id not in db["users"]:
        db["users"][user_id] = {
            "bakiye": 0.0,
            "iban": generate_iban(),
            "kart_no": generate_card_number(),
            "skt": "12/28",
            "cvv": str(random.randint(100, 999)),
            "kredi_borcu": 0.0,
            "kredi_notu": 1000,
            "kredi_gun_sayisi": 0,
            "durum": "aktif"
        }
        save_db(db)
    if "durum" not in db["users"][user_id]: db["users"][user_id]["durum"] = "aktif"
    if "kredi_notu" not in db["users"][user_id]: db["users"][user_id]["kredi_notu"] = 1000
    return db["users"][user_id]

# --- GÖRSEL KREDİ KARTI ÜRETİCİ ---
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

# --- YÖNETİCİ ONAY/RED BUTONLARI ---
class TalepOnayView(discord.ui.View):
    def __init__(self, req_id, bot):
        super().__init__(timeout=None)
        self.req_id = req_id
        self.bot = bot

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
            db["kasa"] = round(db["kasa"] + talep["toplam"], 2)
        elif talep["tur"] == "kredi":
            db["users"][user_id]["bakiye"] = round(db["users"][user_id]["bakiye"] + talep["tutar"], 2)
            db["users"][user_id]["kredi_borcu"] = round(db["users"][user_id]["kredi_borcu"] + talep["tutar"], 2)
            db["users"][user_id]["kredi_gun_sayisi"] = 0
        elif talep["tur"] == "para_cekme":
            db["kasa"] = round(db["kasa"] + talep["komisyon"], 2)
        elif talep["tur"] == "para_yatirma":
            db["users"][user_id]["bakiye"] = round(db["users"][user_id]["bakiye"] + talep["tutar"], 2)

        del db["bekleyen_talepler"][self.req_id]
        save_db(db)
        await auto_backup(self.bot)

        for child in self.children: child.disabled = True
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

        if talep["tur"] in ["satin_alim", "para_cekme"]:
            db["users"][user_id]["bakiye"] = round(db["users"][user_id]["bakiye"] + talep["toplam"], 2)

        del db["bekleyen_talepler"][self.req_id]
        save_db(db)
        await auto_backup(self.bot)

        for child in self.children: child.disabled = True
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "⛔ İşlem Reddedildi"
        await interaction.response.edit_message(embed=embed, view=self)

# --- İNTERAKTİF MENÜ (DROPDOWN) ---
class HelpSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Odeme Yap", description="Kredi kartı ile ürün satın al", emoji="🛍️"),
            discord.SelectOption(label="Taksitlendir", description="Ürünü taksitlendir", emoji="💳"),
            discord.SelectOption(label="Para Cek", description="Kasadan nakit çek", emoji="🏧"),
            discord.SelectOption(label="Para Yatir", description="Kasaya para yatır", emoji="💵"),
            discord.SelectOption(label="Kredi Cek", description="Bankadan kredi talep et", emoji="📑"),
            discord.SelectOption(label="Kredi Ode", description="Kredi borcunu öde", emoji="💸"),
            discord.SelectOption(label="Havale Yap", description="IBAN'a para yolla", emoji="🔄")
        ]
        super().__init__(placeholder="Hızlı İşlem Seçiniz...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        hedef_id = str(interaction.user.id)
        bot_ref = interaction.client
        secim = self.values[0]

        if secim == "Odeme Yap": await interaction.response.send_modal(OdemeModal(hedef_id, bot_ref))
        elif secim == "Taksitlendir": await interaction.response.send_modal(TaksitModal(hedef_id, bot_ref))
        elif secim == "Para Cek": await interaction.response.send_modal(ParaCekModal(hedef_id, bot_ref))
        elif secim == "Para Yatir": await interaction.response.send_modal(ParaYatirModal(hedef_id, bot_ref))
        elif secim == "Kredi Cek": await interaction.response.send_modal(KrediModal(hedef_id, bot_ref))
        elif secim == "Kredi Ode": await interaction.response.send_modal(KrediOdeModal(hedef_id, bot_ref))
        elif secim == "Havale Yap": await interaction.response.send_modal(HavaleModal(hedef_id, bot_ref))

class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(HelpSelect())

# --- DİNAMİK FORMLAR (MODAL) ---
class OdemeModal(discord.ui.Modal, title="🛍️ Ödeme Formu"):
    fiyat = discord.ui.TextInput(label="Ürün Fiyatı (TL)", placeholder="Örn: 150", required=True)
    kart_no = discord.ui.TextInput(label="Kart Numarası", placeholder="Admin işleminde boş kalabilir", required=False, max_length=19)
    skt = discord.ui.TextInput(label="Son Kullanma Tarihi", placeholder="12/28", required=False, max_length=5)
    cvv = discord.ui.TextInput(label="CVV", placeholder="123", required=False, max_length=3)
    aciklama = discord.ui.TextInput(label="Satın Alınan Ürün / Link", required=True)

    def __init__(self, hedef_id, bot):
        super().__init__()
        self.hedef_id = hedef_id
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        fiyat_val = validate_positive_amount(self.fiyat.value)
        if fiyat_val is None: return await interaction.response.send_message("❌ Geçersiz tutar!", ephemeral=True)

        db = load_db()
        hesap = get_or_create_user(db, self.hedef_id)
        if hesap.get("durum") == "dondurulmus": return await interaction.response.send_message("❌ Hesap bloke!", ephemeral=True)

        is_admin_override = (str(interaction.user.id) != self.hedef_id)
        if not is_admin_override:
            girilen_kart = clean_card_number(self.kart_no.value)
            if girilen_kart != hesap["kart_no"] or clean_skt(self.skt.value) != hesap["skt"] or self.cvv.value.strip() != hesap["cvv"]:
                return await interaction.response.send_message("❌ Girdiğiniz kart bilgileri hatalı!", ephemeral=True)

        komisyon = round(fiyat_val * db["ayarlar"]["komisyon_odeme"], 2)
        toplam = round(fiyat_val + komisyon, 2)

        if hesap["bakiye"] < toplam: return await interaction.response.send_message(f"❌ Bakiye Yetersiz! Toplam: {toplam} ₺", ephemeral=True)

        hesap["bakiye"] = round(hesap["bakiye"] - toplam, 2)
        req_id = generate_req_id()
        db["bekleyen_talepler"][req_id] = {"tur": "satin_alim", "user_id": self.hedef_id, "tutar": fiyat_val, "komisyon": komisyon, "toplam": toplam, "link": self.aciklama.value}
        save_db(db)
        await auto_backup(self.bot)

        embed = discord.Embed(title="⏳ Ödeme Askıya Alındı", color=discord.Color.orange())
        embed.description = "Tutar bakiyeden düşüldü, onay bekleniyor.\n" + ("*(Admin Bypass Aktif)*" if is_admin_override else "")
        embed.add_field(name="Kullanıcı", value=f"<@{self.hedef_id}>")
        embed.add_field(name="Tutar", value=f"{fiyat_val:,.2f} ₺")
        embed.add_field(name="İşlem Kodu", value=f"`{req_id}`")
        await interaction.response.send_message(embed=embed, view=TalepOnayView(req_id, self.bot))

class TaksitModal(discord.ui.Modal, title="💳 Taksitli Alışveriş"):
    fiyat = discord.ui.TextInput(label="Ürün Fiyatı (TL)", required=True)
    taksit = discord.ui.TextInput(label="Taksit Sayısı", required=True)
    kart_no = discord.ui.TextInput(label="Kart Numarası", required=False, max_length=19)
    cvv = discord.ui.TextInput(label="CVV Kodu", required=False, max_length=3)

    def __init__(self, hedef_id, bot):
        super().__init__()
        self.hedef_id = hedef_id
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        fiyat_val = validate_positive_amount(self.fiyat.value)
        try:
            taksit_val = int(self.taksit.value)
            if taksit_val <= 0: raise ValueError
        except: return await interaction.response.send_message("❌ Geçersiz taksit!", ephemeral=True)
        if fiyat_val is None: return await interaction.response.send_message("❌ Geçersiz tutar!", ephemeral=True)

        db = load_db()
        hesap = get_or_create_user(db, self.hedef_id)
        if hesap.get("durum") == "dondurulmus": return await interaction.response.send_message("❌ Hesap bloke!", ephemeral=True)

        is_admin_override = (str(interaction.user.id) != self.hedef_id)
        if not is_admin_override:
            if clean_card_number(self.kart_no.value) != hesap["kart_no"] or self.cvv.value.strip() != hesap["cvv"]:
                return await interaction.response.send_message("❌ Kart bilgileri hatalı!", ephemeral=True)

        toplam_borc = round(fiyat_val + (fiyat_val * db["ayarlar"]["komisyon_odeme"]), 2)
        pesinat = round(toplam_borc / taksit_val, 2)

        if hesap["bakiye"] < pesinat: return await interaction.response.send_message(f"❌ Yetersiz Bakiye! Peşinat: {pesinat} ₺", ephemeral=True)

        req_id = generate_req_id()
        hesap["bakiye"] = round(hesap["bakiye"] - pesinat, 2)
        db["bekleyen_talepler"][req_id] = {"tur": "kredi", "user_id": self.hedef_id, "tutar": round(toplam_borc - pesinat, 2)}
        save_db(db)
        await auto_backup(self.bot)

        embed = discord.Embed(title="⏳ Taksit Beklemede", description=f"Peşinat ({pesinat:,.2f} ₺) kesildi.", color=discord.Color.orange())
        embed.add_field(name="İşlem Kodu", value=f"`{req_id}`")
        await interaction.response.send_message(embed=embed, view=TalepOnayView(req_id, self.bot))

class KrediModal(discord.ui.Modal, title="📑 Kredi Formu"):
    tutar = discord.ui.TextInput(label="Çekilecek Tutar (TL)", required=True)

    def __init__(self, hedef_id, bot):
        super().__init__()
        self.hedef_id = hedef_id
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        tutar_val = validate_positive_amount(self.tutar.value)
        if tutar_val is None: return await interaction.response.send_message("❌ Geçersiz tutar!", ephemeral=True)

        db = load_db()
        hesap = get_or_create_user(db, self.hedef_id)
        if hesap.get("durum") == "dondurulmus": return await interaction.response.send_message("❌ Hesap bloke!", ephemeral=True)
        if hesap["kredi_notu"] < 500: return await interaction.response.send_message("❌ Kredi notu çok düşük!", ephemeral=True)

        req_id = generate_req_id()
        db["bekleyen_talepler"][req_id] = {"tur": "kredi", "user_id": self.hedef_id, "tutar": tutar_val}
        save_db(db)
        await auto_backup(self.bot)

        embed = discord.Embed(title="📑 Kredi Talebi", description=f"<@{self.hedef_id}> için onay bekleniyor.", color=discord.Color.blue())
        embed.add_field(name="İşlem Kodu", value=f"`{req_id}`")
        await interaction.response.send_message(embed=embed, view=TalepOnayView(req_id, self.bot))

class KrediOdeModal(discord.ui.Modal, title="💸 Kredi Borcu Ödeme"):
    tutar = discord.ui.TextInput(label="Ödenecek Tutar (TL)", required=True)

    def __init__(self, hedef_id, bot):
        super().__init__()
        self.hedef_id = hedef_id
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        odeme_val = validate_positive_amount(self.tutar.value)
        if odeme_val is None: return await interaction.response.send_message("❌ Geçersiz tutar!", ephemeral=True)

        db = load_db()
        hesap = get_or_create_user(db, self.hedef_id)
        
        if hesap.get("durum") == "dondurulmus": return await interaction.response.send_message("❌ Hesap bloke!", ephemeral=True)
        if hesap["kredi_borcu"] <= 0: return await interaction.response.send_message("❌ Borç bulunmuyor.", ephemeral=True)
        if hesap["bakiye"] < odeme_val: return await interaction.response.send_message("❌ Bakiye yetersiz.", ephemeral=True)

        if odeme_val > hesap["kredi_borcu"]: odeme_val = hesap["kredi_borcu"]

        hesap["bakiye"] = round(hesap["bakiye"] - odeme_val, 2)
        hesap["kredi_borcu"] = round(hesap["kredi_borcu"] - odeme_val, 2)
        db["kasa"] = round(db["kasa"] + odeme_val, 2)
        hesap["kredi_notu"] += int(odeme_val * 0.05)
        
        if hesap["kredi_borcu"] <= 0:
            hesap["kredi_borcu"], hesap["kredi_gun_sayisi"] = 0.0, 0
            ek_mesaj = "🎉 Borcun tamamı ödendi!"
        else: ek_mesaj = f"Kalan Borç: **{hesap['kredi_borcu']:,.2f} ₺**"

        save_db(db)
        await auto_backup(self.bot)

        embed = discord.Embed(title="✅ Ödeme Alındı", description=f"<@{self.hedef_id}> borcu ödendi.\n{ek_mesaj}", color=discord.Color.green())
        await interaction.response.send_message(embed=embed)

class ParaCekModal(discord.ui.Modal, title="🏧 Para Çekme"):
    tutar = discord.ui.TextInput(label="Çekilecek Tutar (TL)", required=True)

    def __init__(self, hedef_id, bot):
        super().__init__()
        self.hedef_id = hedef_id
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        tutar_val = validate_positive_amount(self.tutar.value)
        if tutar_val is None: return await interaction.response.send_message("❌ Geçersiz tutar!", ephemeral=True)

        db = load_db()
        hesap = get_or_create_user(db, self.hedef_id)
        if hesap.get("durum") == "dondurulmus": return await interaction.response.send_message("❌ Hesap bloke!", ephemeral=True)
        
        komisyon = round(tutar_val * db["ayarlar"]["komisyon_cekme"], 2)
        toplam = round(tutar_val + komisyon, 2)

        if hesap["bakiye"] < toplam: return await interaction.response.send_message(f"❌ Yetersiz Bakiye!", ephemeral=True)

        hesap["bakiye"] = round(hesap["bakiye"] - toplam, 2)
        req_id = generate_req_id()
        db["bekleyen_talepler"][req_id] = {"tur": "para_cekme", "user_id": self.hedef_id, "tutar": tutar_val, "komisyon": komisyon, "toplam": toplam}
        save_db(db)
        await auto_backup(self.bot)

        embed = discord.Embed(title="⏳ Çekim Talebi", description=f"Onay bekleniyor. (İşlem: `{req_id}`)", color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, view=TalepOnayView(req_id, self.bot))

class ParaYatirModal(discord.ui.Modal, title="💵 Para Yatırma"):
    tutar = discord.ui.TextInput(label="Yatırılan Tutar (TL)", required=True)
    kanit = discord.ui.TextInput(label="Açıklama / Dekont Linki", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, hedef_id, bot):
        super().__init__()
        self.hedef_id = hedef_id
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        tutar_val = validate_positive_amount(self.tutar.value)
        if tutar_val is None: return await interaction.response.send_message("❌ Geçersiz tutar!", ephemeral=True)

        db = load_db()
        hesap = get_or_create_user(db, self.hedef_id)
        if hesap.get("durum") == "dondurulmus": return await interaction.response.send_message("❌ Hesap bloke!", ephemeral=True)

        req_id = generate_req_id()
        db["bekleyen_talepler"][req_id] = {"tur": "para_yatirma", "user_id": self.hedef_id, "tutar": tutar_val, "kanit": self.kanit.value}
        save_db(db)
        await auto_backup(self.bot)

        embed = discord.Embed(title="⏳ Yatırma Talebi", description=f"Onay bekleniyor. (İşlem: `{req_id}`)", color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, view=TalepOnayView(req_id, self.bot))

class HavaleModal(discord.ui.Modal, title="🔄 Para Transferi"):
    iban = discord.ui.TextInput(label="Alıcı IBAN", required=True)
    tutar = discord.ui.TextInput(label="Tutar (TL)", required=True)
    aciklama = discord.ui.TextInput(label="Açıklama", required=False)

    def __init__(self, hedef_id, bot):
        super().__init__()
        self.hedef_id = hedef_id
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        tutar_val = validate_positive_amount(self.tutar.value)
        if tutar_val is None: return await interaction.response.send_message("❌ Geçersiz tutar!", ephemeral=True)

        db = load_db()
        gonderen_hesap = get_or_create_user(db, self.hedef_id)
        if gonderen_hesap.get("durum") == "dondurulmus": return await interaction.response.send_message("❌ Gönderici hesap bloke!", ephemeral=True)

        hedef_iban = clean_iban(self.iban.value)
        alici_id = next((uid for uid, data in db["users"].items() if data.get("iban") == hedef_iban), None)

        if not alici_id: return await interaction.response.send_message("❌ IBAN bulunamadı!", ephemeral=True)
        if alici_id == self.hedef_id: return await interaction.response.send_message("❌ Kendine gönderemezsin!", ephemeral=True)
        if db["users"][alici_id].get("durum") == "dondurulmus": return await interaction.response.send_message("❌ Alıcı hesap bloke!", ephemeral=True)

        komisyon = round(tutar_val * db["ayarlar"]["komisyon_havale"], 2) if tutar_val > db["ayarlar"]["havale_sinir"] else 0.0
        toplam = round(tutar_val + komisyon, 2)

        if gonderen_hesap["bakiye"] < toplam: return await interaction.response.send_message(f"❌ Bakiye yetersiz!", ephemeral=True)

        db["users"][self.hedef_id]["bakiye"] = round(db["users"][self.hedef_id]["bakiye"] - toplam, 2)
        db["users"][alici_id]["bakiye"] = round(db["users"][alici_id]["bakiye"] + tutar_val, 2)
        db["kasa"] = round(db["kasa"] + komisyon, 2)
        save_db(db)
        await auto_backup(self.bot)

        embed = discord.Embed(title="✅ Transfer Başarılı", color=discord.Color.green())
        embed.description = f"<@{self.hedef_id}> hesabından {hedef_iban} no'lu hesaba para iletildi."
        await interaction.response.send_message(embed=embed)


# --- BOT KURULUMU VE ZAMANLAYICI ---
class BankBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        faiz_isle.start()

bot = BankBot()

# --- HAFTALIK CEZA VE GÜNLÜK FAİZ SİSTEMİ ---
@tasks.loop(hours=24)
async def faiz_isle():
    db = load_db()
    for user_id, u_data in db["users"].items():
        if u_data.get("kredi_borcu", 0) > 0:
            u_data["kredi_gun_sayisi"] += 1
            gun = u_data["kredi_gun_sayisi"]
            
            # Her 7 günde bir (Haftalık) Ceza ve Faiz biner
            if gun % 7 == 0:
                faiz_orani = db["ayarlar"].get("kredi_faiz", 0.05)
                ceza = db["ayarlar"].get("gecikme_cezasi", 50.0)
                
                u_data["kredi_borcu"] = round((u_data["kredi_borcu"] * (1 + faiz_orani)) + ceza, 2)
                u_data["kredi_notu"] = max(0, u_data["kredi_notu"] - 25)
    save_db(db)
    await auto_backup(bot)

@bot.event
async def on_ready():
    print(f"{bot.user} aktif! Sistem hazır.")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Merkez Bankası Hesapları"))
    
    try:
        synced = await bot.tree.sync()
        print(f"Toplam {len(synced)} slash komutu başarıyla yüklendi (Çiftlenme Önlendi).")
    except Exception as e:
        print(e)

@bot.event
async def on_member_join(member):
    db = load_db()
    get_or_create_user(db, str(member.id))

    guild = member.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    for role in guild.roles:
        if role.permissions.administrator:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    try:
        await guild.create_text_channel(f"💳・{member.name}-hesap", overwrites=overwrites)
    except: pass

# --- KULLANICI KOMUTLARI ---
@bot.tree.command(name="help", description="Tüm banka komutlarını interaktif menüde listeler.")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🏦 Merkez Bankası İnteraktif Menü", description="Lütfen aşağıdaki açılır menüden yapmak istediğiniz işlemi seçin. Komut yazmanıza gerek yoktur.", color=discord.Color.blurple())
    await interaction.response.send_message(embed=embed, view=HelpView())

@bot.tree.command(name="hesap-bilgi", description="Banka hesabının güncel durumunu gösterir.")
async def hesap_bilgi(interaction: discord.Interaction):
    db = load_db()
    hesap = get_or_create_user(db, str(interaction.user.id))
    
    durum_yazi = "🟢 Aktif" if hesap.get("durum") == "aktif" else "🔴 Bloke Edilmiş"
    embed = discord.Embed(title="🏦 Merkez Bankası Hesap Özeti", color=discord.Color.gold())
    embed.add_field(name="💰 Bakiye", value=f"**{hesap['bakiye']:,.2f} ₺**", inline=False)
    embed.add_field(name="🏛️ IBAN", value=f"```{hesap['iban']}```", inline=False)
    embed.add_field(name="📉 Kredi Borcu", value=f"{hesap['kredi_borcu']:,.2f} ₺ (Gün: {hesap.get('kredi_gun_sayisi', 0)})", inline=True)
    embed.add_field(name="Durum", value=durum_yazi, inline=True)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="kredi-notum", description="Banka kredi notunu gösterir.")
async def kredi_notum(interaction: discord.Interaction):
    db = load_db()
    notu = get_or_create_user(db, str(interaction.user.id))["kredi_notu"]
    
    if notu >= 1500: s, r = "Platin", discord.Color.green()
    elif notu >= 1000: s, r = "Altın", discord.Color.gold()
    elif notu >= 500: s, r = "Riskli", discord.Color.orange()
    else: s, r = "Çok Riskli", discord.Color.red()

    embed = discord.Embed(title="📈 Kredi Notunuz", description=f"Puan: **{notu}** ({s})", color=r)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="kartim", description="Banka kartını görsel olarak atar.")
async def kartim(interaction: discord.Interaction):
    db = load_db()
    hesap = get_or_create_user(db, str(interaction.user.id))
    if hesap.get("durum") == "dondurulmus": return await interaction.response.send_message("❌ Hesap bloke!", ephemeral=True)
    
    card_img = generate_credit_card(interaction.user.display_name, hesap["kart_no"], hesap["skt"], hesap["cvv"])
    file = discord.File(card_img, filename="kredi_karti.png")
    
    embed = discord.Embed(title="💳 Dijital Kredi Kartınız", color=discord.Color.dark_purple())
    embed.add_field(name="Kopyalanabilir Bilgiler", value=f"Kart: `{hesap['kart_no']}` | SKT: `{hesap['skt']}` | CVV: `{hesap['cvv']}`\nIBAN: `{hesap['iban']}`")
    embed.set_image(url="attachment://kredi_karti.png")
    await interaction.response.send_message(embed=embed, file=file, ephemeral=True)

# --- KULLANICI / YÖNETİCİ DİNAMİK FİNANSAL KOMUTLARI ---
def get_target(interaction, kullanici):
    if kullanici and not interaction.user.guild_permissions.administrator: return None
    return str(kullanici.id) if kullanici else str(interaction.user.id)

@bot.tree.command(name="odeme-yap", description="Kredi kartı ile ürün satın alma formu.")
async def cmd_odeme(interaction: discord.Interaction, kullanici: discord.Member = None):
    hedef = get_target(interaction, kullanici)
    if not hedef: return await interaction.response.send_message("❌ Başkası adına işlem yetkiniz yok!", ephemeral=True)
    await interaction.response.send_modal(OdemeModal(hedef, bot))

@bot.tree.command(name="taksitlendir", description="Ürünü taksitlendirme formu.")
async def cmd_taksit(interaction: discord.Interaction, kullanici: discord.Member = None):
    hedef = get_target(interaction, kullanici)
    if not hedef: return await interaction.response.send_message("❌ Başkası adına işlem yetkiniz yok!", ephemeral=True)
    await interaction.response.send_modal(TaksitModal(hedef, bot))

@bot.tree.command(name="kredi-cek", description="Kredi başvuru formu.")
async def cmd_kredi_cek(interaction: discord.Interaction, kullanici: discord.Member = None):
    hedef = get_target(interaction, kullanici)
    if not hedef: return await interaction.response.send_message("❌ Başkası adına işlem yetkiniz yok!", ephemeral=True)
    await interaction.response.send_modal(KrediModal(hedef, bot))

@bot.tree.command(name="kredi-ode", description="Birikmiş kredi borcunu ödeme formu.")
async def cmd_kredi_ode(interaction: discord.Interaction, kullanici: discord.Member = None):
    hedef = get_target(interaction, kullanici)
    if not hedef: return await interaction.response.send_message("❌ Başkası adına işlem yetkiniz yok!", ephemeral=True)
    await interaction.response.send_modal(KrediOdeModal(hedef, bot))

@bot.tree.command(name="para-cek", description="Kasadan çekim formu.")
async def cmd_para_cek(interaction: discord.Interaction, kullanici: discord.Member = None):
    hedef = get_target(interaction, kullanici)
    if not hedef: return await interaction.response.send_message("❌ Başkası adına işlem yetkiniz yok!", ephemeral=True)
    await interaction.response.send_modal(ParaCekModal(hedef, bot))

@bot.tree.command(name="para-yatir", description="Kasaya para yatırma formu.")
async def cmd_para_yatir(interaction: discord.Interaction, kullanici: discord.Member = None):
    hedef = get_target(interaction, kullanici)
    if not hedef: return await interaction.response.send_message("❌ Başkası adına işlem yetkiniz yok!", ephemeral=True)
    await interaction.response.send_modal(ParaYatirModal(hedef, bot))

@bot.tree.command(name="havale", description="IBAN ile havale formu.")
async def cmd_havale(interaction: discord.Interaction, kullanici: discord.Member = None):
    hedef = get_target(interaction, kullanici)
    if not hedef: return await interaction.response.send_message("❌ Başkası adına işlem yetkiniz yok!", ephemeral=True)
    await interaction.response.send_modal(HavaleModal(hedef, bot))

# --- YÖNETİCİ ÖZEL KOMUTLARI ---
@bot.tree.command(name="hesap-bak", description="[YÖNETİCİ] Etiketlenen kullanıcının banka hesabını tam sorgular.")
@app_commands.default_permissions(administrator=True)
async def hesap_bak(interaction: discord.Interaction, kullanici: discord.Member):
    db = load_db()
    hesap = get_or_create_user(db, str(kullanici.id))
    embed = discord.Embed(title=f"🔍 {kullanici.display_name} - Detaylı Sorgulama", color=discord.Color.blue())
    embed.add_field(name="💰 Bakiye", value=f"**{hesap['bakiye']:,.2f} ₺**", inline=True)
    embed.add_field(name="📉 Kredi Borcu", value=f"**{hesap['kredi_borcu']:,.2f} ₺**", inline=True)
    embed.add_field(name="📈 Kredi Notu", value=f"**{hesap['kredi_notu']}**", inline=True)
    embed.add_field(name="🏛️ IBAN", value=f"`{hesap['iban']}`", inline=False)
    embed.add_field(name="💳 Kart No", value=f"`{hesap['kart_no']}`", inline=True)
    embed.add_field(name="Durum", value="🟢 Aktif" if hesap.get("durum") == "aktif" else "🔴 Bloke", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="bakiye-ver", description="[YÖNETİCİ] Bir kullanıcıya bakiye ekler.")
@app_commands.default_permissions(administrator=True)
async def bakiye_ver(interaction: discord.Interaction, kullanici: discord.Member, miktar: float):
    db = load_db()
    hesap = get_or_create_user(db, str(kullanici.id))
    hesap["bakiye"] = round(hesap["bakiye"] + miktar, 2)
    save_db(db)
    await auto_backup(bot)
    await interaction.response.send_message(f"✅ {kullanici.mention} hesabına **{miktar:,.2f} ₺** eklendi.")

@bot.tree.command(name="toplu-bakiye-ver", description="[YÖNETİCİ] Belirli bir role sahip herkese maaş/bakiye dağıtır.")
@app_commands.default_permissions(administrator=True)
async def toplu_bakiye_ver(interaction: discord.Interaction, rol: discord.Role, miktar: float):
    db = load_db()
    kisi_sayisi = 0
    for member in rol.members:
        hesap = get_or_create_user(db, str(member.id))
        hesap["bakiye"] = round(hesap["bakiye"] + miktar, 2)
        kisi_sayisi += 1
    
    save_db(db)
    await auto_backup(bot)
    await interaction.response.send_message(f"✅ **{rol.name}** rolündeki **{kisi_sayisi}** kişiye toplam **{miktar * kisi_sayisi:,.2f} ₺** bakiye dağıtıldı.")

@bot.tree.command(name="hesap-mudahale", description="[YÖNETİCİ] IBAN üzerinden kullanıcının bakiyesine el koyar/ekler.")
@app_commands.default_permissions(administrator=True)
async def hesap_mudahale(interaction: discord.Interaction, iban: str, eklenecek_tutar: float):
    db = load_db()
    hedef_iban = clean_iban(iban)
    hedef_id = next((uid for uid, data in db["users"].items() if data.get("iban") == hedef_iban), None)
            
    if not hedef_id: return await interaction.response.send_message("❌ Bu IBAN'a ait hesap bulunamadı.", ephemeral=True)
        
    db["users"][hedef_id]["bakiye"] = round(db["users"][hedef_id]["bakiye"] + eklenecek_tutar, 2)
    save_db(db)
    await auto_backup(bot)
    await interaction.response.send_message(f"✅ **{hedef_iban}** nolu hesaba müdahale edildi. Yeni Bakiye: **{db['users'][hedef_id]['bakiye']:,.2f} ₺**")

@bot.tree.command(name="kredi-yapilandir", description="[YÖNETİCİ] Borcu şişen kullanıcının faiz döngüsünü sıfırlar.")
@app_commands.default_permissions(administrator=True)
async def kredi_yapilandir(interaction: discord.Interaction, kullanici: discord.Member, yeni_borc_tutari: float):
    db = load_db()
    hesap = get_or_create_user(db, str(kullanici.id))
    hesap["kredi_borcu"] = round(yeni_borc_tutari, 2)
    hesap["kredi_gun_sayisi"] = 0
    save_db(db)
    await auto_backup(bot)
    await interaction.response.send_message(f"✅ {kullanici.mention} kullanıcısının borcu **{yeni_borc_tutari:,.2f} ₺** olarak sabitlendi ve faiz gün sayacı sıfırlandı.")

@bot.tree.command(name="hesap-dondur", description="[YÖNETİCİ] Şüpheli kullanıcının banka hesabını kilitler.")
@app_commands.default_permissions(administrator=True)
async def hesap_dondur(interaction: discord.Interaction, kullanici: discord.Member):
    db = load_db()
    hesap = get_or_create_user(db, str(kullanici.id))
    hesap["durum"] = "dondurulmus"
    save_db(db)
    await auto_backup(bot)
    await interaction.response.send_message(f"🔴 {kullanici.mention} adlı kullanıcının banka hesabı **donduruldu/bloke edildi**.")

@bot.tree.command(name="hesap-ac", description="[YÖNETİCİ] Bloke edilen banka hesabını tekrar aktif eder.")
@app_commands.default_permissions(administrator=True)
async def hesap_ac(interaction: discord.Interaction, kullanici: discord.Member):
    db = load_db()
    hesap = get_or_create_user(db, str(kullanici.id))
    hesap["durum"] = "aktif"
    save_db(db)
    await auto_backup(bot)
    await interaction.response.send_message(f"🟢 {kullanici.mention} adlı kullanıcının banka hesabı tekrar **aktif** edildi.")

@bot.tree.command(name="komisyon-ayarla", description="[YÖNETİCİ] Sistem komisyon oranlarını ayarlar (Örn: %5 için 0.05 yazın).")
@app_commands.describe(tur="Hangi komisyon değişecek?", oran="Yeni oran (0.05 = %5)")
@app_commands.choices(tur=[
    app_commands.Choice(name="Ödeme Komisyonu", value="komisyon_odeme"),
    app_commands.Choice(name="Çekim Komisyonu", value="komisyon_cekme"),
    app_commands.Choice(name="Havale Komisyonu", value="komisyon_havale")
])
@app_commands.default_permissions(administrator=True)
async def komisyon_ayarla(interaction: discord.Interaction, tur: app_commands.Choice[str], oran: float):
    db = load_db()
    db["ayarlar"][tur.value] = oran
    save_db(db)
    await auto_backup(bot)
    await interaction.response.send_message(f"✅ **{tur.name}** başarıyla **%{int(oran*100)}** olarak güncellendi!")

@bot.tree.command(name="ceza-ayarla", description="[YÖNETİCİ] Kredi faiz oranını ve haftalık gecikme cezasını belirler.")
@app_commands.default_permissions(administrator=True)
async def ceza_ayarla(interaction: discord.Interaction, faiz_yuzdesi: float, gecikme_cezasi_tl: float):
    db = load_db()
    db["ayarlar"]["kredi_faiz"] = faiz_yuzdesi / 100
    db["ayarlar"]["gecikme_cezasi"] = gecikme_cezasi_tl
    save_db(db)
    await auto_backup(bot)
    await interaction.response.send_message(f"✅ **Faiz Oranı:** %{faiz_yuzdesi} | **Haftalık Sabit Ceza:** {gecikme_cezasi_tl} ₺ olarak ayarlandı.")

@bot.tree.command(name="log-kanal-ayarla", description="[YÖNETİCİ] Otomatik db yedeklerinin atılacağı kanalı seçer.")
@app_commands.default_permissions(administrator=True)
async def log_kanal_ayarla(interaction: discord.Interaction, kanal: discord.TextChannel):
    db = load_db()
    db["ayarlar"]["log_kanal_id"] = kanal.id
    save_db(db)
    await interaction.response.send_message(f"✅ Otomatik `.json` yedekleme kanalı {kanal.mention} olarak ayarlandı.")
    await auto_backup(bot)

@bot.tree.command(name="json-yedekle", description="[YÖNETİCİ] Veritabanını manuel olarak indirir.")
@app_commands.default_permissions(administrator=True)
async def json_yedekle(interaction: discord.Interaction):
    await interaction.response.send_message("📂 Güncel Veritabanı:", file=discord.File(DB_FILE, filename="bank_db_yedek.json"), ephemeral=True)

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

    if sum(sizes) == 0: sizes = [1, 1, 1]

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

if TOKEN:
    keep_alive()
    bot.run(TOKEN)
