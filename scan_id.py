import os
import argparse
import tempfile
import re
import logging

# Desativa logs verbosos do PaddleOCR no terminal
logging.getLogger("ppocr").setLevel(logging.WARNING)

from thefuzz import fuzz
from paddleocr import PaddleOCR
from flask import Flask, request, jsonify

app = Flask(__name__)

print("Iniciando o leitor de OCR globalmente (PaddleOCR)...")
try:
    ocr_engine = PaddleOCR(use_angle_cls=True, lang='pt', show_log=False)
except Exception as e:
    print(f"Erro crítico ao inicializar o PaddleOCR global: {e}")
    ocr_engine = None

def get_proximity_and_correct(text):
    FI = "FILIAÇÃO"
    DN = "DATA NASC."
    NT = "NATURALIDADE"
    NI = "NAO INFORMADO"
    CNH = "CNH"
    CM = "CERT.MILITAR"
    CPF = "CPF"
    RG = "REGISTRO GERAL"
    
    extracted_info = {}
    for line in text.split("\n"):
        if line.strip():
            # Utiliza similaridade (distância de Levenshtein) para encontrar chaves, já que o OCR costuma errar letras.
            for keyword in [FI, DN, NT, NI, CNH, CM, CPF, RG]:
                if fuzz.partial_ratio(keyword, line) > 80:
                    extracted_info[keyword] = line.strip()
    return extracted_info

@app.route('/scan', methods=['POST'])
def scan_brazil_id():
    verso_points = 0
    frente_points = 0
    
    if 'image' not in request.files:
        return jsonify({"erro": "Nenhuma imagem foi recebida."}), 400
        
    image_file = request.files['image']
    if image_file.filename == '':
        return jsonify({"erro": "Nenhum arquivo de imagem foi selecionado."}), 400
        
    print(f"Escaneando o documento: {image_file.filename}")
    
    # PaddleOCR as vezes tem problemas ao ler bytes diretos em memória dependendo do Wrapper, 
    # por garantia salvamos a imagem do upload em um arquivo local temporário que é descartado depois.
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp:
        image_file.save(temp.name)
        temp_image_path = temp.name

    if ocr_engine is None:
        if os.path.exists(temp_image_path):
            os.remove(temp_image_path)
        return jsonify({"erro": "Motor de OCR não foi carregado corretamente"}), 500
    
    print("Rodando a extração do OCR no documento...")
    try:
        result = ocr_engine.ocr(temp_image_path, cls=True)
    except Exception as e:
        print(f"Erro crítico durante a extração de texto OCR: {e}")
        if os.path.exists(temp_image_path):
            os.remove(temp_image_path)
        return jsonify({"erro": "Erro interno durante o processamento do OCR"}), 500
    finally:
        if os.path.exists(temp_image_path):
            os.remove(temp_image_path)
    
    extracted_text = []
    if not result or all(res is None for res in result):
        print("Nenhum texto detectado na imagem.")
        return jsonify({
            "extracted_text": [],
            "key_information": {},
            "document_info": {"cpf": None, "rg": None, "dates": [], "type": "Unknown"}
        }), 200
        
    print("\n--- Texto Bruto Extraído pelo OCR ---")
    for idx in range(len(result)):
        res = result[idx]
        if res is None:
            continue
        for line in res:
            # line[1][0] contém a string reconhecida
            # line[1][1] contém a taxa de confiança daquele texto
            text = line[1][0]
            confidence = line[1][1]
            extracted_text.append(text)
            print(f"'{text}' (Confiança: {confidence:.2f})")
            
    # Junta todo o texto extraído em um bloção só para as heurísticas de Regex.
    full_text = "\n".join(extracted_text)
    
    print("\n--- Processo Heurístico (Filtragem e Extração de Chaves) ---")
    key_info = get_proximity_and_correct(full_text)
    
    document_info = {
        "cpf": None,
        "rg": None,
        "dates": [],
        "type": "Unknown"
    }

    # Regex p/ CPF: Captura de 000.000.000-00 a 00000000000. 
    # Não forçamos limitadores de palavra (\b) porque o OCR do celular costuma emendar letras e números sem espaço (ex: "CPF123456").
    cpf_match = re.search(r'\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\s]?\d{2}', full_text)
    if cpf_match:
        document_info["cpf"] = cpf_match.group(0)
        print(f"CPF: {cpf_match.group(0)}")
        verso_points += 1
    else:
        print("CPF: Não encontrado.")
        frente_points += 1
        
    # Regex p/ RG: O RG varia muito no BR mas costuma ser "12.345.678-9".
    # Pela mesma mecânica do CPF, não se usa limitador para perdoar OCR falho. O dígito verificador pode ser "X".
    rg_match = re.search(r'\d{1,2}[\.\s]?\d{3}[\.\s]?\d{3}[-\s]?[0-9X]', full_text, re.IGNORECASE)
    if rg_match and rg_match.group(0) != (cpf_match.group(0) if cpf_match else ""):
        document_info["rg"] = rg_match.group(0)
        print(f"Registro Geral (RG): {rg_match.group(0)}")
        verso_points += 1
    else:
        print("Registro Geral (RG): Não encontrado.")
        frente_points += 1
    
    dates_info = []
    # Capturamos todas as datas (dd/mm/aaaa) mas pegamos junto os 30 caracteres antes E os 30 caracteres depois.
    # O objetivo pegar essa "janela" é descobrir qual o rótulo daquela data caso a palavra caia perto dela.
    for match in re.finditer(r'(.{0,30})(\d{2}/\d{2}/\d{4})(.{0,30})', full_text, flags=re.DOTALL):
        context_before = match.group(1).upper()
        date_str = match.group(2)
        context_after = match.group(3).upper()
        context = context_before + context_after
        
        if "NASC" in context:
            identifier = "Data de Nascimento"
        elif "EXP" in context or "EMIS" in context:
            identifier = "Data de Expedição"
        else:
            # Fallback: Se não encontrarmos uma menção explícita de "Nascimento/Expedição", a gente "chuta" 
            # pegando a última palavra literal grudada antes da data (ou a primeira depois, se vier vazio).
            fallback_match = re.search(r'([A-ZÀ-Ÿ]+)[^A-ZÀ-Ÿ]*$', context_before)
            if fallback_match:
                identifier = fallback_match.group(1)
            else:
                fallback_match_after = re.search(r'^[^A-ZÀ-Ÿ]*([A-ZÀ-Ÿ]+)', context_after)
                identifier = fallback_match_after.group(1) if fallback_match_after else "Unknown"
            
        dates_info.append({
            "date": date_str,
            "identifier": identifier
        })

    if dates_info:
        document_info["dates"] = dates_info
        print(f"Data(s) extraída(s): {', '.join([d['date'] + ' (' + d['identifier'] + ')' for d in dates_info])}")
        frente_points += 1
    else:
        print("Datas extraídas: Nenhuma identificada.")
        verso_points += 1

    if frente_points > verso_points and verso_points == 0:
        document_info["type"] = "frente"
        print("Foto tirada apenas da frente")
    elif frente_points != 0 and verso_points != 0:
        document_info["type"] = "ambos"
        print("Foto tirada da frente e do verso")
    else:
        document_info["type"] = "verso"
        print("Foto tirada apenas do verso")

    return jsonify({
        "extracted_text": extracted_text,
        "key_information": key_info,
        "document_info": document_info
    }), 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
