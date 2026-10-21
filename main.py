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
                "havale_sinir": 100.0
            }
        }
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
        if "ayarlar" not in db:
            db["ayarlar"] = {"komisyon_odeme": 0.60, "komisyon_cekme": 0.10, "komisyon_havale": 0.05, "havale_sinir": 100.0}
        return db

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def generate_iban():
    return "TR" + "".join([str(random.randint(0, 9)) for _ in range(24)])

def generate_card_number():
    return "4444 " + " ".join(["".join([str(random.randint(0, 9)) for _ in range(4)]) for _ in range(3)])

def generate_req_id():
    return "REQ-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

# --- BİÇİMLENDİRME YARDIMCILARI ---
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
        if math.isnan(val) or math.isinf(val) or val <= 0:
            return None
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
    if "durum" not in db["users"][user_id]:
        db["users"][user_id]["durum"] = "aktif"
    if "kredi_notu" not in db["users"][user_id]:
        db["users"][user_id]["kredi_notu"] = 1000
    return db["users"][user_id]

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

# --- YÖNETİCİ ONAY/RED BUTONLARI ---
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
            db["users"][user_id]["kredi_gun_sayisi"] = 0
        elif talep["tur"] == "para_cekme":
            db["kasa"] += talep["komisyon"]
        elif talep["tur"] == "para_yatirma":
            db["users"][user_id]["bakiye"] += talep["tutar"]

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

        if talep["tur"] in ["satin_alim", "para_cekme"]:
            db["users"][user_id]["bakiye"] += talep["toplam"]

        del db["bekleyen_talepler"][self.req_id]
        save_db(db)

        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "⛔ İşlem Reddedildi"
        await interaction.response.edit_message(embed=embed, view=self)

# --- POP-UP KUTUCUKLAR (MODAL/FORM SİSTEMİ) ---

class OdemeModal(discord.ui.Modal, title="🛍️ Kredi Kartı ile Ödeme Formu"):
    fiyat = discord.ui.TextInput(label="Ürün Fiyatı (TL)", placeholder="Örn: 150", required=True)
    kart_no = discord.ui.TextInput(label="Kart Numarası", placeholder="4444 1234 ...", required=True, max_length=19)
    skt = discord.ui.TextInput(label="Son Kullanma Tarihi", placeholder="12/28 veya 1228", required=True, max_length=5)
    cvv = discord.ui.TextInput(label="CVV", placeholder="123", required=True, max_length=3)
    aciklama = discord.ui.TextInput(label="Satın Alınan Ürün / Link", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        fiyat_val = validate_positive_amount(self.fiyat.value)
        if fiyat_val is None:
            return await interaction.response.send_message("❌ Geçersiz tutar! Lütfen 0'dan büyük pozitif sayı girin.", ephemeral=True)

        db = load_db()
        user_id = str(interaction.user.id)
        hesap = get_or_create_user(db, user_id)
        
        if hesap.get("durum") == "dondurulmus":
            return await interaction.response.send_message("❌ Hesabınız bloke edilmiştir. İşlem yapamazsınız.", ephemeral=True)

        girilen_kart = clean_card_number(self.kart_no.value)
        girilen_skt = clean_skt(self.skt.value)
        
        if girilen_kart != hesap["kart_no"] or girilen_skt != hesap["skt"] or self.cvv.value.strip() != hesap["cvv"]:
            return await interaction.response.send_message("❌ **İşlem Reddedildi:** Girdiğiniz kart bilgileri hatalı!", ephemeral=True)

        komisyon_orani = db["ayarlar"]["komisyon_odeme"]
        kesilecek_komisyon = round(fiyat_val * komisyon_orani, 2)
        toplam_tutar = round(fiyat_val + kesilecek_komisyon, 2)

        if hesap["bakiye"] < toplam_tutar:
            return await interaction.response.send_message(f"❌ Bakiye Yetersiz! Ürün + %{int(komisyon_orani*100)} Vergi için **{toplam_tutar:,.2f} ₺** gerekiyor.", ephemeral=True)

        hesap["bakiye"] -= toplam_tutar
        req_id = generate_req_id()

        db["bekleyen_talepler"][req_id] = {
            "tur": "satin_alim", "user_id": user_id, "tutar": fiyat_val, "komisyon": kesilecek_komisyon, "toplam": toplam_tutar, "link": self.aciklama.value
        }
        save_db(db)

        embed = discord.Embed(title="⏳ Ödeme Askıya Alındı", color=discord.Color.orange())
        embed.description = f"Satın alım tutarı bakiyeden düşüldü, **Onay** bekleniyor."
        embed.add_field(name="Ürün/Link", value=self.aciklama.value, inline=False)
        embed.add_field(name="Tutar", value=f"{fiyat_val:,.2f} ₺")
        embed.add_field(name=f"Vergi (%{int(komisyon_orani*100)})", value=f"{kesilecek_komisyon:,.2f} ₺")
        embed.add_field(name="İşlem Kodu", value=f"`{req_id}`")

        await interaction.response.send_message(embed=embed, view=TalepOnayView(req_id))

class TaksitModal(discord.ui.Modal, title="💳 Taksitli Alışveriş"):
    fiyat = discord.ui.TextInput(label="Ürün Fiyatı (TL)", required=True)
    taksit = discord.ui.TextInput(label="Taksit Sayısı (Örn: 3, 6, 9)", required=True)
    kart_no = discord.ui.TextInput(label="Kart Numarası", required=True, max_length=19)
    cvv = discord.ui.TextInput(label="CVV Kodu", required=True, max_length=3)

    async def on_submit(self, interaction: discord.Interaction):
        fiyat_val = validate_positive_amount(self.fiyat.value)
        try:
            taksit_val = int(self.taksit.value)
            if taksit_val <= 0: raise ValueError
        except ValueError:
            return await interaction.response.send_message("❌ Geçersiz taksit sayısı!", ephemeral=True)

        if fiyat_val is None:
            return await interaction.response.send_message("❌ Geçersiz tutar!", ephemeral=True)

        db = load_db()
        user_id = str(interaction.user.id)
        hesap = get_or_create_user(db, user_id)
        if hesap.get("durum") == "dondurulmus":
            return await interaction.response.send_message("❌ Hesabınız bloke edilmiştir.", ephemeral=True)

        girilen_kart = clean_card_number(self.kart_no.value)
        if girilen_kart != hesap["kart_no"] or self.cvv.value.strip() != hesap["cvv"]:
            return await interaction.response.send_message("❌ **İşlem Reddedildi:** Girdiğiniz kart bilgileri hatalı!", ephemeral=True)

        toplam_borc = round(fiyat_val + (fiyat_val * db["ayarlar"]["komisyon_odeme"]), 2)
        pesinat = round(toplam_borc / taksit_val, 2)

        if hesap["bakiye"] < pesinat:
            return await interaction.response.send_message(f"❌ Bakiye Yetersiz! İlk taksit olan **{pesinat:,.2f} ₺** ödenemiyor.", ephemeral=True)

        req_id = generate_req_id()
        db["users"][user_id]["bakiye"] -= pesinat
        
        db["bekleyen_talepler"][req_id] = {
            "tur": "kredi",
            "user_id": user_id,
            "tutar": round(toplam_borc - pesinat, 2),
            "aciklama": "Taksitli Alım İşlemi"
        }
        save_db(db)

        embed = discord.Embed(title="⏳ Taksitli İşlem Askıya Alındı", color=discord.Color.orange())
        embed.description = f"İlk taksit (**{pesinat:,.2f} ₺**) kesildi. Kalan tutar onaylanınca kredi borcunuza yansıyacaktır."
        embed.add_field(name="İşlem Kodu", value=f"`{req_id}`")
        await interaction.response.send_message(embed=embed, view=TalepOnayView(req_id))

class KrediModal(discord.ui.Modal, title="📑 Kredi Başvuru Formu"):
    tutar = discord.ui.TextInput(label="Çekmek İstediğiniz Tutar (TL)", placeholder="Örn: 5000", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        tutar_val = validate_positive_amount(self.tutar.value)
        if tutar_val is None:
            return await interaction.response.send_message("❌ Geçersiz tutar!", ephemeral=True)

        db = load_db()
        user_id = str(interaction.user.id)
        hesap = get_or_create_user(db, user_id)
        if hesap.get("durum") == "dondurulmus":
            return await interaction.response.send_message("❌ Hesabınız bloke edilmiştir.", ephemeral=True)
        if hesap["kredi_notu"] < 500:
            return await interaction.response.send_message("❌ Kredi notunuz çok düşük (500 altı). Kredi çekemezsiniz.", ephemeral=True)

        req_id = generate_req_id()
        db["bekleyen_talepler"][req_id] = {"tur": "kredi", "user_id": user_id, "tutar": tutar_val}
        save_db(db)

        embed = discord.Embed(title="📑 Kredi Talebi Oluşturuldu", color=discord.Color.blue())
        embed.description = f"**{tutar_val:,.2f} ₺** kredi talebiniz yönetici onayına sunuldu.\n_Onaylanırsa her 10 günde bir katlanan faiz işlemeye başlar._"
        embed.add_field(name="İşlem Kodu", value=f"`{req_id}`")
        await interaction.response.send_message(embed=embed, view=TalepOnayView(req_id))

class KrediOdeModal(discord.ui.Modal, title="💸 Kredi Borcu Ödeme"):
    tutar = discord.ui.TextInput(label="Ödenecek Tutar (TL)", placeholder="Örn: 1500", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        odeme_val = validate_positive_amount(self.tutar.value)
        if odeme_val is None:
            return await interaction.response.send_message("❌ Geçersiz tutar! Lütfen 0'dan büyük pozitif sayı girin.", ephemeral=True)

        db = load_db()
        user_id = str(interaction.user.id)
        hesap = get_or_create_user(db, user_id)
        
        if hesap.get("durum") == "dondurulmus":
            return await interaction.response.send_message("❌ Hesabınız bloke edilmiştir.", ephemeral=True)
        
        if hesap["kredi_borcu"] <= 0:
            return await interaction.response.send_message("❌ Zaten kredi borcunuz bulunmuyor.", ephemeral=True)
            
        if hesap["bakiye"] < odeme_val:
            return await interaction.response.send_message("❌ Bakiyeniz yetersiz. Borç ödemek için hesabınızda nakit bulunmalı.", ephemeral=True)

        if odeme_val > hesap["kredi_borcu"]:
            odeme_val = hesap["kredi_borcu"]

        hesap["bakiye"] = round(hesap["bakiye"] - odeme_val, 2)
        hesap["kredi_borcu"] = round(hesap["kredi_borcu"] - odeme_val, 2)
        db["kasa"] = round(db["kasa"] + odeme_val, 2)
        
        hesap["kredi_notu"] += int(odeme_val * 0.05)

        if hesap["kredi_borcu"] <= 0:
            hesap["kredi_borcu"] = 0.0
            hesap["kredi_gun_sayisi"] = 0
            ek_mesaj = "🎉 Borcunuzun tamamı ödendi! Faiz sayacı sıfırlandı."
        else:
            ek_mesaj = f"Kalan Kredi Borcunuz: **{hesap['kredi_borcu']:,.2f} ₺**"

        save_db(db)

        embed = discord.Embed(title="✅ Kredi Ödemesi Alındı", color=discord.Color.green())
        embed.add_field(name="Ödenen Tutar", value=f"**{odeme_val:,.2f} ₺**", inline=False)
        embed.add_field(name="Yeni Kredi Notunuz", value=f"{hesap['kredi_notu']} 📈", inline=False)
        embed.description = ek_mesaj
        await interaction.response.send_message(embed=embed)

class ParaCekModal(discord.ui.Modal, title="🏧 Para Çekme Formu"):
    tutar = discord.ui.TextInput(label="Çekmek İstediğiniz Tutar (TL)", placeholder="Örn: 500", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        tutar_val = validate_positive_amount(self.tutar.value)
        if tutar_val is None:
            return await interaction.response.send_message("❌ Geçersiz tutar!", ephemeral=True)

        db = load_db()
        user_id = str(interaction.user.id)
        hesap = get_or_create_user(db, user_id)
        if hesap.get("durum") == "dondurulmus":
            return await interaction.response.send_message("❌ Hesabınız bloke edilmiştir.", ephemeral=True)
        
        komisyon_orani = db["ayarlar"]["komisyon_cekme"]
        komisyon = round(tutar_val * komisyon_orani, 2)
        toplam_dusulecek = round(tutar_val + komisyon, 2)

        if hesap["bakiye"] < toplam_dusulecek:
            return await interaction.response.send_message(f"❌ Yetersiz Bakiye! Çekim + %{int(komisyon_orani*100)} Komisyon için **{toplam_dusulecek:,.2f} ₺** gerekiyor.", ephemeral=True)

        hesap["bakiye"] -= toplam_dusulecek
        req_id = generate_req_id()
        db["bekleyen_talepler"][req_id] = {"tur": "para_cekme", "user_id": user_id, "tutar": tutar_val, "komisyon": komisyon, "toplam": toplam_dusulecek}
        save_db(db)

        embed = discord.Embed(title="⏳ Para Çekme Talebi", color=discord.Color.orange())
        embed.description = f"**{tutar_val:,.2f} ₺** çekim talebi onay bekliyor. Toplam **{toplam_dusulecek:,.2f} ₺** bakiyeden askıya alındı."
        embed.add_field(name="İşlem Kodu", value=f"`{req_id}`")
        await interaction.response.send_message(embed=embed, view=TalepOnayView(req_id))

class ParaYatirModal(discord.ui.Modal, title="💵 Para Yatırma Formu"):
    tutar = discord.ui.TextInput(label="Yatırılan Tutar (TL)", placeholder="Örn: 1000", required=True)
    kanit = discord.ui.TextInput(label="Açıklama / Dekont Linki", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        tutar_val = validate_positive_amount(self.tutar.value)
        if tutar_val is None:
            return await interaction.response.send_message("❌ Geçersiz tutar!", ephemeral=True)

        db = load_db()
        user_id = str(interaction.user.id)
        hesap = get_or_create_user(db, user_id)
        if hesap.get("durum") == "dondurulmus":
            return await interaction.response.send_message("❌ Hesabınız bloke edilmiştir.", ephemeral=True)

        req_id = generate_req_id()
        db["bekleyen_talepler"][req_id] = {"tur": "para_yatirma", "user_id": user_id, "tutar": tutar_val, "kanit": self.kanit.value}
        save_db(db)

        embed = discord.Embed(title="⏳ Para Yatırma Talebi", color=discord.Color.blue())
        embed.description = f"**{tutar_val:,.2f} ₺** yatırma talebi yönetici onayına sunuldu. (Komisyon Yok)"
        embed.add_field(name="Kanıt/Açıklama", value=self.kanit.value, inline=False)
        embed.add_field(name="İşlem Kodu", value=f"`{req_id}`")
        await interaction.response.send_message(embed=embed, view=TalepOnayView(req_id))

class HavaleModal(discord.ui.Modal, title="🔄 Para Transferi (Havale/EFT)"):
    iban = discord.ui.TextInput(label="Alıcı IBAN", placeholder="TR...", required=True)
    tutar = discord.ui.TextInput(label="Gönderilecek Tutar (TL)", placeholder="Örn: 250", required=True)
    aciklama = discord.ui.TextInput(label="Açıklama", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        tutar_val = validate_positive_amount(self.tutar.value)
        if tutar_val is None:
            return await interaction.response.send_message("❌ Geçersiz tutar!", ephemeral=True)

        db = load_db()
        gonderen_id = str(interaction.user.id)
        gonderen_hesap = get_or_create_user(db, gonderen_id)

        if gonderen_hesap.get("durum") == "dondurulmus":
            return await interaction.response.send_message("❌ Hesabınız bloke edilmiştir.", ephemeral=True)

        hedef_iban = clean_iban(self.iban.value)
        alici_id = None
        for uid, data in db["users"].items():
            if data.get("iban") == hedef_iban:
                alici_id = uid
                break

        if not alici_id:
            return await interaction.response.send_message("❌ Belirtilen IBAN'a ait hesap bulunamadı!", ephemeral=True)
        if alici_id == gonderen_id:
            return await interaction.response.send_message("❌ Kendinize para gönderemezsiniz!", ephemeral=True)
        if db["users"][alici_id].get("durum") == "dondurulmus":
            return await interaction.response.send_message("❌ Alıcının hesabı bloke durumda olduğu için para gönderilemiyor.", ephemeral=True)

        komisyon = 0.0
        if tutar_val > db["ayarlar"]["havale_sinir"]:
            komisyon = round(tutar_val * db["ayarlar"]["komisyon_havale"], 2)
        
        toplam_dusulecek = round(tutar_val + komisyon, 2)

        if gonderen_hesap["bakiye"] < toplam_dusulecek:
            return await interaction.response.send_message(f"❌ Yetersiz Bakiye! Gönderim + Komisyon için **{toplam_dusulecek:,.2f} ₺** gerekiyor.", ephemeral=True)

        db["users"][gonderen_id]["bakiye"] = round(db["users"][gonderen_id]["bakiye"] - toplam_dusulecek, 2)
        db["users"][alici_id]["bakiye"] = round(db["users"][alici_id]["bakiye"] + tutar_val, 2)
        db["kasa"] = round(db["kasa"] + komisyon, 2)
        save_db(db)

        embed = discord.Embed(title="✅ Transfer Başarılı (Anında Dekont)", color=discord.Color.green())
        embed.add_field(name="Gönderilen", value=f"{tutar_val:,.2f} ₺")
        embed.add_field(name="Kesilen Komisyon", value=f"{komisyon:,.2f} ₺")
        embed.add_field(name="Alıcı IBAN", value=f"`{hedef_iban}`")
        if self.aciklama.value:
            embed.add_field(name="Açıklama", value=self.aciklama.value, inline=False)

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

# --- KATLANAN GÜNLÜK FAİZ ZAMANLAYICISI ---
@tasks.loop(hours=24)
async def faiz_isle():
    db = load_db()
    for user_id, user_data in db["users"].items():
        if user_data.get("kredi_borcu", 0) > 0:
            user_data["kredi_gun_sayisi"] += 1
            gun = user_data["kredi_gun_sayisi"]
            
            ekstra_oran = (gun // 10) * 0.02
            toplam_faiz_orani = 0.02 + ekstra_oran
            user_data["kredi_borcu"] = round(user_data["kredi_borcu"] * (1 + toplam_faiz_orani), 2)

            if gun % 10 == 0: 
                user_data["kredi_notu"] -= 15
                if user_data["kredi_notu"] < 0: user_data["kredi_notu"] = 0
                
    save_db(db)

@bot.event
async def on_ready():
    print(f"{bot.user} aktif! Sistem 7/24 çalışmaya hazır.")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Borsa ve Kurları"))
    
    for guild in bot.guilds:
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    print("Tüm slash komutları (/) sunuculara anında tanımlandı!")

@bot.event
async def on_guild_join(guild):
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)

@bot.event
async def on_member_join(member):
    db = load_db()
    get_or_create_user(db, str(member.id))

    guild = member.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        member: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    try:
        await guild.create_text_channel(f"💳・{member.name}-hesap", overwrites=overwrites)
    except Exception:
        pass

# --- KULLANICI KOMUTLARI ---
@bot.tree.command(name="help", description="Tüm banka komutlarını listeler.")
async def help_cmd(interaction: discord.Interaction):
    is_admin = interaction.user.guild_permissions.administrator
    embed = discord.Embed(title="🏦 Merkez Bankası Menüsü", color=discord.Color.blurple())
    
    user_cmds = """
    `/hesap-bilgi` - Hesap detaylarını gösterir.
    `/kredi-notum` - Banka puanını ve durumunu gösterir.
    `/kartim` - Görsel banka kartını üretir ve kopyalanabilir bilgileri atar.
    `/odeme-yap` - Form açarak kredi kartı ile ürün satın alır.
    `/taksitlendir` - Ürünü kart ile taksitle alıp kalanı borca ekler.
    `/havale` - Başka bir IBAN'a anında para yollar.
    `/para-cek` - Kasadan nakit çekim talebi oluşturur.
    `/para-yatir` - Kasaya nakit yatırma talebi oluşturur.
    `/kredi-cek` - Bankadan faizli kredi talep eder.
    `/kredi-ode` - Birikmiş kredi borcunu bakiyenden öder.
    """
    embed.add_field(name="👤 Müşteri Komutları", value=user_cmds, inline=False)
    
    if is_admin:
        admin_cmds = """
        `/bakiye-ver` - Bir kullanıcıya bakiye ekler.
        `/toplu-bakiye-ver` - Belirli bir role toplu maaş dağıtır.
        `/hesap-mudahale` - IBAN'dan direkt para ekler/keser.
        `/hesap-dondur` - Şüpheli kullanıcının hesabını kilitler.
        `/hesap-ac` - Kilitli hesabı tekrar aktif eder.
        `/kredi-yapilandir` - Borcu batanın borcunu yapılandırır.
        `/komisyon-ayarla` - İşlem komisyonlarını günceller.
        `/kasa-grafik` - Kasa pasta grafiğini çizer.
        `/json-yedekle` - Veritabanını indirir.
        """
        embed.add_field(name="🛠️ Yönetici Komutları", value=admin_cmds, inline=False)
        
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="hesap-bilgi", description="Banka hesabının güncel durumunu gösterir.")
async def hesap_bilgi(interaction: discord.Interaction):
    db = load_db()
    hesap = get_or_create_user(db, str(interaction.user.id))
    
    durum_yazi = "🟢 Aktif" if hesap.get("durum") == "aktif" else "🔴 Bloke Edilmiş"
    embed = discord.Embed(title="🏦 Merkez Bankası Hesap Özeti", color=discord.Color.gold())
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    embed.add_field(name="💰 Güncel Bakiye", value=f"**{hesap['bakiye']:,.2f} ₺**", inline=False)
    embed.add_field(name="🏛️ IBAN", value=f"`{hesap['iban']}`", inline=False)
    embed.add_field(name="📉 Kredi Borcu", value=f"{hesap['kredi_borcu']:,.2f} ₺ (Gün: {hesap.get('kredi_gun_sayisi', 0)})", inline=True)
    embed.add_field(name="Durum", value=durum_yazi, inline=True)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="kredi-notum", description="Findeks benzeri banka kredi notunu gösterir.")
async def kredi_notum(interaction: discord.Interaction):
    db = load_db()
    hesap = get_or_create_user(db, str(interaction.user.id))
    notu = hesap["kredi_notu"]
    
    if notu >= 1500: seviye, renk = "Çok İyi (Platin)", discord.Color.green()
    elif notu >= 1000: seviye, renk = "İyi (Altın)", discord.Color.gold()
    elif notu >= 500: seviye, renk = "Riskli", discord.Color.orange()
    else: seviye, renk = "Çok Riskli (Kredi Çekemez)", discord.Color.red()

    embed = discord.Embed(title="📈 Kredi Notu Durumunuz", color=renk)
    embed.add_field(name="Puanınız", value=f"**{notu}**", inline=False)
    embed.add_field(name="Seviye", value=seviye, inline=False)
    embed.set_footer(text="Borcunuzu düzenli ödedikçe notunuz artar, geciktirdikçe düşer.")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="kartim", description="Banka kartını ve kopyalanabilir bilgilerini atar.")
async def kartim(interaction: discord.Interaction):
    db = load_db()
    hesap = get_or_create_user(db, str(interaction.user.id))
    
    if hesap.get("durum") == "dondurulmus":
        return await interaction.response.send_message("❌ Hesabınız bloke edildiği için kartınıza erişemezsiniz.", ephemeral=True)
    
    card_img = generate_credit_card(interaction.user.display_name, hesap["kart_no"], hesap["skt"], hesap["cvv"])
    file = discord.File(card_img, filename="kredi_karti.png")
    
    embed = discord.Embed(title="💳 Dijital Kredi Kartınız", color=discord.Color.dark_purple())
    embed.description = "Aşağıdaki bilgilerin üzerine tıklayarak kopyalayabilirsiniz:"
    embed.add_field(name="Kart Numarası", value=f"```{hesap['kart_no']}```", inline=False)
    embed.add_field(name="Son Kullanma Tarihi", value=f"```{hesap['skt']}```", inline=True)
    embed.add_field(name="CVV", value=f"```{hesap['cvv']}```", inline=True)
    embed.add_field(name="IBAN", value=f"```{hesap['iban']}```", inline=False)
    embed.set_image(url="attachment://kredi_karti.png")
    
    await interaction.response.send_message(embed=embed, file=file, ephemeral=True)

@bot.tree.command(name="kredi-ode", description="Birikmiş kredi borcunu bakiyenden ödersin.")
async def kredi_ode(interaction: discord.Interaction):
    await interaction.response.send_modal(KrediOdeModal())

@bot.tree.command(name="odeme-yap", description="Satın almak istediğin ürün için kredi kartı doğrulama kutucuğunu açar.")
async def odeme_yap(interaction: discord.Interaction):
    await interaction.response.send_modal(OdemeModal())

@bot.tree.command(name="taksitlendir", description="Satın almak istediğin ürünü kartla takside böler.")
async def taksitlendir(interaction: discord.Interaction):
    await interaction.response.send_modal(TaksitModal())

@bot.tree.command(name="kredi-cek", description="Kredi başvurusu yapmak için form kutucuğunu açar.")
async def kredi_cek(interaction: discord.Interaction):
    await interaction.response.send_modal(KrediModal())

@bot.tree.command(name="para-cek", description="Hesabından para çekme formu açar (%10 komisyonlu).")
async def para_cek(interaction: discord.Interaction):
    await interaction.response.send_modal(ParaCekModal())

@bot.tree.command(name="para-yatir", description="Hesabına para yatırma formu açar (Komisyonsuz).")
async def para_yatir(interaction: discord.Interaction):
    await interaction.response.send_modal(ParaYatirModal())

@bot.tree.command(name="havale", description="Başka bir hesaba IBAN ile anında para yollar.")
async def havale(interaction: discord.Interaction):
    await interaction.response.send_modal(HavaleModal())

# --- YÖNETİCİ KOMUTLARI ---
@bot.tree.command(name="bakiye-ver", description="[YÖNETİCİ] Bir kullanıcıya bakiye ekler.")
@app_commands.default_permissions(administrator=True)
async def bakiye_ver(interaction: discord.Interaction, kullanici: discord.Member, miktar: float):
    db = load_db()
    hesap = get_or_create_user(db, str(kullanici.id))
    hesap["bakiye"] = round(hesap["bakiye"] + miktar, 2)
    save_db(db)
    
    embed = discord.Embed(title="💰 Bakiye Tanımlandı", color=discord.Color.green())
    embed.description = f"{kullanici.mention} hesabına **{miktar:,.2f} ₺** eklendi.\nGüncel Bakiye: **{hesap['bakiye']:,.2f} ₺**"
    await interaction.response.send_message(embed=embed)

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
    await interaction.response.send_message(f"✅ **{rol.name}** rolündeki **{kisi_sayisi}** kişiye toplam **{miktar * kisi_sayisi:,.2f} ₺** bakiye dağıtıldı.")

@bot.tree.command(name="hesap-mudahale", description="[YÖNETİCİ] IBAN üzerinden kullanıcının bakiyesine el koyar/ekler.")
@app_commands.default_permissions(administrator=True)
async def hesap_mudahale(interaction: discord.Interaction, iban: str, eklenecek_tutar: float):
    db = load_db()
    hedef_iban = clean_iban(iban)
    hedef_id = None
    for uid, data in db["users"].items():
        if data.get("iban") == hedef_iban:
            hedef_id = uid
            break
            
    if not hedef_id:
        return await interaction.response.send_message("❌ Bu IBAN'a ait hesap bulunamadı.", ephemeral=True)
        
    db["users"][hedef_id]["bakiye"] = round(db["users"][hedef_id]["bakiye"] + eklenecek_tutar, 2)
    save_db(db)
    await interaction.response.send_message(f"✅ **{hedef_iban}** nolu hesaba müdahale edildi. Yeni Bakiye: **{db['users'][hedef_id]['bakiye']:,.2f} ₺**")

@bot.tree.command(name="kredi-yapilandir", description="[YÖNETİCİ] Borcu şişen kullanıcının faiz döngüsünü sıfırlar.")
@app_commands.default_permissions(administrator=True)
async def kredi_yapilandir(interaction: discord.Interaction, kullanici: discord.Member, yeni_borc_tutari: float):
    db = load_db()
    hesap = get_or_create_user(db, str(kullanici.id))
    hesap["kredi_borcu"] = round(yeni_borc_tutari, 2)
    hesap["kredi_gun_sayisi"] = 0
    save_db(db)
    await interaction.response.send_message(f"✅ {kullanici.mention} kullanıcısının borcu **{yeni_borc_tutari:,.2f} ₺** olarak sabitlendi ve faiz gün sayacı sıfırlandı.")

@bot.tree.command(name="hesap-dondur", description="[YÖNETİCİ] Şüpheli kullanıcının banka hesabını kilitler.")
@app_commands.default_permissions(administrator=True)
async def hesap_dondur(interaction: discord.Interaction, kullanici: discord.Member):
    db = load_db()
    hesap = get_or_create_user(db, str(kullanici.id))
    hesap["durum"] = "dondurulmus"
    save_db(db)
    await interaction.response.send_message(f"🔴 {kullanici.mention} adlı kullanıcının banka hesabı **donduruldu/bloke edildi**.")

@bot.tree.command(name="hesap-ac", description="[YÖNETİCİ] Bloke edilen banka hesabını tekrar aktif eder.")
@app_commands.default_permissions(administrator=True)
async def hesap_ac(interaction: discord.Interaction, kullanici: discord.Member):
    db = load_db()
    hesap = get_or_create_user(db, str(kullanici.id))
    hesap["durum"] = "aktif"
    save_db(db)
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
    await interaction.response.send_message(f"✅ **{tur.name}** başarıyla **%{int(oran*100)}** olarak güncellendi!")

@bot.tree.command(name="json-yedekle", description="[YÖNETİCİ] Veritabanını anlık olarak indirir.")
@app_commands.default_permissions(administrator=True)
async def json_yedekle(interaction: discord.Interaction):
    file = discord.File(DB_FILE, filename="bank_db_yedek.json")
    await interaction.response.send_message("📂 Güncel veritabanı yedeği alındı:", file=file, ephemeral=True)

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

if TOKEN:
    keep_alive()
    bot.run(TOKEN)
