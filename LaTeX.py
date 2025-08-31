import tkinter as tk
from tkinter import filedialog, messagebox
import os
import shutil
import tempfile
from PIL import Image, ImageTk 

# --- Fonctions de traitement du texte ---

import re

def _normalize_apostrophes(s: str) -> str:
    return s.replace("’", "'")

def clean_latex(s: str) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    s = re.sub(r"^↳\s*Feedback\s*:.*$", "", s, flags=re.MULTILINE|re.IGNORECASE)
    s = re.sub(r"(?mi)^\s*É?e?noncé\s*:\s*", "", s)
    s = re.sub(r"\[.*?EB\d*.*?\]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\[.*?Consigne.*?\]", "", s, flags=re.IGNORECASE)

    # transformer \( ... \) en $...$ (même multi-lignes)
    def repl_math(m: re.Match) -> str:
        inner = m.group(1)
        inner = " ".join(inner.split())
        return f"${inner}$"
    s = re.sub(r"\\\((.*?)\\\)", repl_math, s, flags=re.DOTALL)

    s = _normalize_apostrophes(s)
    s = re.sub(r"[ \t]+", " ", s)
    return s

def format_title(text: str) -> str:
    text = _normalize_apostrophes(text or "").strip()
    text = re.sub(r"[ \t]+", " ", text)
    return text

def format_question_block(q_type: str, question_id: int, title: str, body: str, choices: list[str]) -> str:
    title_clean = clean_latex(title)
    title_clean = re.sub(r"(?i)^\s*Question\s*\d+\s*[:\-]?\s*", "", title_clean).strip()
    paragraph_title = f"{q_type} {question_id} : {format_title(title_clean)}".strip()

    latex = clean_latex(body).rstrip() + "\n\n"
    latex += f"\\paragraph{{{paragraph_title}}}\n"
    if choices:
        latex += "\\begin{enumerate}[label=\\Alph*.]\n"
        for choice in choices:
            latex += f"    \\item {clean_latex(choice)}\n"
        latex += "\\end{enumerate}\n"
    latex += "\n\\vspace{0.5cm}\n\n"
    return latex

def format_data_block(body_lines: list[str]) -> str:
    joined = "\n".join([l for l in body_lines if (l or '').strip()])
    if not joined.strip():
        return ""
    return "\\textbf{Donnée :}\n\n" + clean_latex(joined) + "\n\\vspace{0.5cm}\n\n"

def parse_questions(txt: str) -> list[str]:
    output: list[str] = []
    blocks = re.split(r"(?mi)^Question\s+\d+\s*:\s*", txt)
    question_id = 1

    for block in blocks[1:]:
        parts = [p for p in block.strip().splitlines()]
        q_type: str | None = None
        title: str = ""
        pre_qcm_lines: list[str] = []
        post_qcm_lines: list[str] = []
        choices: list[str] = []
        itemize_buffer: list[str] = []
        found_qcm_line = False

        def flush_itemize(target_lines: list[str]) -> None:
            nonlocal itemize_buffer
            if itemize_buffer:
                target_lines.append("\\begin{itemize}")
                for item in itemize_buffer:
                    target_lines.append(f"  \\item {clean_latex(item)}")
                target_lines.append("\\end{itemize}")
                itemize_buffer = []

        for raw in parts:
            line = (raw or "").strip()
            if not line:
                continue

            if re.match(r"^↳\s*Feedback\s*:", line, flags=re.IGNORECASE):
                continue

            # détecter "QCM|QCS|QSC 01 : ..."
            match_type = re.search(r"(?i)(QCM|QCS|QSC)\s*(\d*)\s*:\s*(.*)$", line)
            if match_type:
                flush_itemize(pre_qcm_lines)
                found_qcm_line = True
                q_type_raw = match_type.group(1).upper()
                q_type = "QCS" if q_type_raw == "QSC" else q_type_raw
                if match_type.group(2).isdigit():
                    question_id = int(match_type.group(2))
                tail = (match_type.group(3) or '').strip()
                if tail:
                    title = tail
                continue

        
            choice_with_label = re.match(r"^-\s*([A-Z])\s*[\.\)]\s*(.+)$", line)
    
            choice_dash_any = re.match(r"^-\s+(.+)$", line)

            if not found_qcm_line:

                if choice_with_label:
                    flush_itemize(pre_qcm_lines)
                    found_qcm_line = True
                    if not q_type:
                        q_type = "QCM"
                    choices.append(choice_with_label.group(2).strip())
                    continue

                # Si on voit un item "- texte" (sans lettre), on considère aussi que c'est un QCM implicite
                if choice_dash_any:
                    flush_itemize(pre_qcm_lines)
                    found_qcm_line = True
                    if not q_type:
                        q_type = "QCM"
                    # retirer éventuellement un label initial "A." collé après le tiret (ex: "- A. ...")
                    text = choice_dash_any.group(1).strip()
                    text = re.sub(r"^[A-Z]\s*[\.\)]\s*", "", text)
                    choices.append(text)
                    continue

                # puces d'info "•" avant QCM
                if line.startswith("•"):
                    itemize_buffer.append(line.lstrip("• ").strip())
                else:
                    flush_itemize(pre_qcm_lines)
                    pre_qcm_lines.append(line)
                continue

            # --- après l'entrée en mode QCM ---
            if choice_with_label:
                choices.append(choice_with_label.group(2).strip())
            elif choice_dash_any:
                text = choice_dash_any.group(1).strip()
                text = re.sub(r"^[A-Z]\s*[\.\)]\s*", "", text)
                choices.append(text)
            elif line.startswith("-"):
                # cas fallback : "- texte" (défensive)
                choices.append(line.lstrip("- ").strip())
            elif line.startswith("•"):
                itemize_buffer.append(line.lstrip("• ").strip())
            else:
                flush_itemize(post_qcm_lines)
                post_qcm_lines.append(line)

        flush_itemize(post_qcm_lines)

        # si pas de titre explicite, on prend la dernière ligne de l’énoncé
        if not title:
            seq = [l for l in post_qcm_lines if l.strip()]
            if seq:
                title = seq[-1]
                post_qcm_lines = post_qcm_lines[:-1]
            else:
                seq2 = [l for l in pre_qcm_lines if l.strip()]
                if seq2:
                    title = seq2[-1]
                    pre_qcm_lines = pre_qcm_lines[:-1]

        raw_body = "\n".join(pre_qcm_lines + post_qcm_lines).strip()

        if q_type:
            output.append(format_question_block(q_type, question_id, title, raw_body, choices))
            question_id += 1
        else:
            output.append(format_data_block(pre_qcm_lines + post_qcm_lines))

    return output

def parse_and_join(txt: str) -> str:
    return "".join(parse_questions(txt))



# --- Fonction principale de conversion ---

def convert_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        raw_text = f.read()

    questions = parse_questions(raw_text)

    tex_filename = os.path.splitext(os.path.basename(filepath))[0] + "_formate.tex"
    temp_dir = tempfile.mkdtemp()
    tex_output_path = os.path.join(temp_dir, tex_filename)

    with open(tex_output_path, 'w', encoding='utf-8') as f:
        f.write(r"""\documentclass{article}
\usepackage[absolute]{textpos}
\usepackage{chngpage}
\usepackage{geometry}
\geometry{ a4paper, margin=2cm }
\usepackage[parfill]{parskip}  
\usepackage{graphicx}
\usepackage{amssymb}
\usepackage{amsmath}
\usepackage{mathtools}
\usepackage{epstopdf}
\usepackage[frenchb]{babel}
\frenchbsetup{StandardLists=true}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{helvet}
\usepackage{sectsty}
\usepackage{titlesec}
\titleformat{\subsection}
 {\normalfont\fontsize{11pt}{12pt}\selectfont\sffamily}
 {\thesubsection}
 {1em}
 {}
\usepackage{enumerate}
\usepackage{enumitem}
\usepackage{multirow}
\usepackage{fancyhdr}
\usepackage{ulem}
\usepackage{lastpage}
\usepackage[squaren, Gray, cdot]{SIunits}
\newcommand{\noyau}[3]{\prescript{#2}{#3}{\mathrm{#1}}}
\usepackage{tabularx}
\makeatletter
\setkeys{Gin}{width=\ifdim\Gin@nat@width>\linewidth \linewidth \else \Gin@nat@width \fi}
\renewcommand{\arraystretch}{1.5}
\setlength{\tabcolsep}{0.4cm}
\newcommand\Dotfill{\leavevmode\cleaders\hb@xt@ .33em{\hss .\hss}\hfill\kern\z@}
\def\trait{\leavevmode\leaders\hrule height 1pt\hfill\kern\z@}
\def\maketitle{%
\null
\thispagestyle{empty}
\normalfont
\begin{sffamily}
\begin{center}\leavevmode
\textbf {EB X PASS}\par
\vspace{0.2cm}
\textbf \@date \par
\vspace{0.9cm}
{\LARGE \textbf \@title\par}
\trait\par
\vspace{1.0cm}
\textbf{Durée : 60 min}\par
\textbf{Documents et calculatrices interdits.}\par
\vspace{0.4cm}
\textbf{RECOMMANDATIONS IMPORTANTES \\ AVANT DE COMMENCER L'EPREUVE}\\
\vspace{0.8cm}
Vous avez à votre disposition un fascicule de X questions.\par
\textbf{(Réponses à reporter sur la grille de QCM)}\\
\vspace{1cm}
Assurez-vous que ce fascicule comporte bien X pages en comptant celle-ci.\\
Dans le cas contraire, prévenez immédiatement un tuteur.\par
\vspace{0.4cm}
\textbf{AUCUNE RECLAMATION NE SERA ADMISE PAR LA SUITE}\\
\vspace{1cm}
\textbf{OBLIGATIONS CONCERNANT LA FEUILLE DE REPONSES AUX QCM} 
\end{center}
\end{sffamily}
\begin{sffamily}
Vous devez absolument utiliser un stylo ou un feutre noir pour cocher votre réponse définitive sur la feuille de réponses. Il est vivement conseillé de remplir tout d'abord cette feuille au crayon (vous pouvez gommer), puis repasser les réponses à l'encre. Les feuilles de réponses remplies au crayon seront affectées de la note zéro.\par
\vspace{0.4cm}
Vous ne devez normalement remplir que la première des deux lignes prévues pour la réponse à chaque question. En cas d'erreur à l'encre, vous devez utiliser la seconde ligne prévue pour chaque question. En cas d'erreurs multiples, il vaut mieux remplir une nouvelle feuille où vous devrez reporter :
\end{sffamily}
\vspace{0.4cm}
\begin{sffamily}
\begin{center}
\textbf{NOM, PRENOM, MATIERE, NUMERO ETUDIANT}
~\\
\vspace{0.5cm}
\begin{center}
    \includegraphics[width=1.5cm]{logo tuto.png}
\end{center}\\
\vspace{0.3cm}
~\\
\textbf{\textit{Ce sujet a été entièrement réalisé par le Tutorat.\\
Ni les professeurs ni la faculté ne pourront être tenus responsables de la validité des informations qu'il contient, même en cas d'une éventuelle relecture par un professeur.}}
~\\
~\\
\textbf{\textit{Tous droits réservés au Tutorat de TSSU.\\Sauf autorisation, la vente ou la rediffusion totale ou partielle des présents QCM sont interdites.}}
\end{center}
\end{sffamily}
\cleardoublepage
}
\makeatother
\title{UEX : X}
\date{Date 2025}
\begin{document}
\maketitle
""")

        for q in questions:
            f.write(q + "\n")

        f.write(r"""
\vspace{1cm}
\uline{\textbf{Message de vos RMs :\\}}
Texte
\end{document}
""")
        



#interface graphique


    script_dir = os.path.dirname(__file__)
    logo_path = os.path.join(script_dir, "logo tuto.png")
    if os.path.exists(logo_path):
        shutil.copy(logo_path, os.path.join(temp_dir, "logo tuto.png"))
    else:
        print("⚠️ 'logo tuto.png' introuvable à côté du script.")

    # Créer le zip
    zip_output_path = os.path.splitext(filepath)[0] + "_overleaf.zip"
    shutil.make_archive(zip_output_path.replace(".zip", ""), 'zip', temp_dir)

    shutil.rmtree(temp_dir)

    return zip_output_path

def choose_file():
    filepath = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
    if filepath:
        try:
            output = convert_file(filepath)
            messagebox.showinfo("Succès", f"Conversion terminée !\nProjet Overleaf prêt :\n{output}")
        except Exception as e:
            messagebox.showerror("Erreur", f"Une erreur est survenue : {str(e)}")

# --- Configuration de l'interface graphique ---
root = tk.Tk()
root.title("Convertisseur LaTeX")
root.geometry("400x350") # Augmente la taille pour le logo
root.configure(bg="white") # Fond blanc

# Ajout du logo
script_dir = os.path.dirname(__file__)
logo_path = os.path.join(script_dir, "logo tuto.png")
if os.path.exists(logo_path):
    # Ouvre et redimensionne l'image pour l'affichage dans Tkinter
    img = Image.open(logo_path)
    img = img.resize((64, 75), Image.Resampling.LANCZOS) # Redimensionne le logo
    photo = ImageTk.PhotoImage(img)
    logo_label = tk.Label(root, image=photo, bg="white")
    logo_label.image = photo # Garde une référence pour éviter que l'image ne soit supprimée par le garbage collector
    logo_label.pack(pady=10)
else:
    print("⚠️ 'logo tuto.png' introuvable pour l'affichage dans l'interface graphique.")

label = tk.Label(
    root,
    text="Dépose ton fichier .txt d'examen pour le convertir en LaTeX",
    wraplength=350,
    bg="white",
    fg="#018BB9"
)
label.pack(pady=10)

button = tk.Button(
    root,
    text="Choisir un fichier .txt",
    command=choose_file,
    bg="white",
    fg="#018BB9",
    activebackground="#FFFFFF",
    activeforeground="#018BB9",
    font=("Arial", 12)
)
button.pack(pady=10)

label = tk.Label(
    root,
    text="TSSU - Tous droits réservés",
    wraplength=350,
    bg="white",
    fg="#018BB9"
)
label.pack(pady=10)

label = tk.Label(
    root,
    text="Crée par Mathiiz, le contacter pour tout problème ou suggestion ;)",
    wraplength=350,
    bg="white",
    fg="#018BB9"
)
label.pack(pady=10)

root.mainloop()


#--- Fin du code ---
# Code par Mathiiz pour TSSU
