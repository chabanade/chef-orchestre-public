// Le Pupitre - logique de l'interface. Pur JavaScript, aucune dependance,
// aucune etape de build : ce fichier est lisible et auditable en entier.
// Il ne parle QU'A son propre serveur local (meme origine) ; il ne connait
// aucune adresse de cloud. Tout passe par le Chef d'Orchestre cote serveur.

"use strict";

let conversationActive = null;

const $ = (sel) => document.querySelector(sel);
const fil = $("#fil");
const liste = $("#liste-conversations");
const saisie = $("#saisie");

// --- appels au serveur local --------------------------------------------
async function api(chemin, options) {
  const rep = await fetch(chemin, options);
  if (!rep.ok) throw new Error("HTTP " + rep.status);
  return rep.status === 204 ? null : rep.json();
}

async function chargerConversations() {
  const convs = await api("/api/conversations");
  liste.innerHTML = "";
  for (const c of convs) {
    const li = document.createElement("li");
    li.textContent = c.titre;
    li.dataset.id = c.id;
    li.className = (c.id === conversationActive) ? "active" : "";
    li.addEventListener("click", () => ouvrirConversation(c.id));
    liste.appendChild(li);
  }
}

async function ouvrirConversation(id) {
  conversationActive = id;
  const messages = await api(`/api/conversations/${id}/messages`);
  fil.innerHTML = "";
  for (const m of messages) ajouterBulle(m.role, m.contenu);
  await chargerConversations(); // pour surligner l'active
  saisie.focus();
}

async function nouvelleConversation() {
  const c = await api("/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ titre: "Nouvelle conversation" }),
  });
  await ouvrirConversation(c.id);
}

// --- affichage ----------------------------------------------------------
function ajouterBulle(role, texte) {
  const div = document.createElement("div");
  div.className = "bulle " + role;
  div.textContent = texte;
  fil.appendChild(div);
  fil.scrollTop = fil.scrollHeight;
  return div;
}

function ajouterAvis(texte) {
  // Refus du routeur (fail-closed), reponse vide... : un avis, pas un message.
  const div = document.createElement("div");
  div.className = "avis";
  div.textContent = texte;
  fil.appendChild(div);
  fil.scrollTop = fil.scrollHeight;
}

// --- documents (RAG local) ----------------------------------------------
async function chargerDocuments() {
  const docs = await api("/api/documents");
  const ul = $("#liste-documents");
  ul.innerHTML = "";
  for (const d of docs) {
    const li = document.createElement("li");
    li.innerHTML = `<span>${d.source}</span><button title="Retirer">✕</button>`;
    li.querySelector("button").addEventListener("click", async (e) => {
      e.stopPropagation();
      await api("/api/documents/" + encodeURIComponent(d.source), { method: "DELETE" });
      await chargerDocuments();
    });
    ul.appendChild(li);
  }
}

async function deposerDocument(fichier) {
  const fd = new FormData();
  fd.append("fichier", fichier);
  const li = document.createElement("li");
  li.textContent = "… " + fichier.name;
  $("#liste-documents").prepend(li);
  try {
    const rep = await fetch("/api/documents", { method: "POST", body: fd });
    if (!rep.ok) {
      const err = await rep.json().catch(() => ({}));
      ajouterAvis("Document refuse : " + (err.detail || rep.status));
    }
  } catch (e) {
    ajouterAvis("Echec du depot du document.");
  }
  await chargerDocuments();
}

// --- envoi --------------------------------------------------------------
async function envoyer(texte) {
  if (!conversationActive) await nouvelleConversation();
  ajouterBulle("user", texte);
  const attente = ajouterBulle("assistant", "...");
  attente.classList.add("attente");

  let res;
  try {
    res = await api("/api/envoyer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: conversationActive,
        message: texte,
        rag: $("#rag").checked,
      }),
    });
  } catch (e) {
    attente.remove();
    ajouterAvis("Erreur : le serveur du Pupitre est injoignable.");
    return;
  }
  attente.remove();

  if (res.type === "message") {
    ajouterBulle("assistant", res.contenu);
  } else if (res.type === "refus") {
    // On montre la raison exacte du refus du Chef d'Orchestre.
    let detail = "";
    if (res.detail && typeof res.detail === "object") {
      detail = res.detail.erreur || res.detail.message || JSON.stringify(res.detail);
    } else if (res.detail) {
      detail = String(res.detail);
    }
    ajouterAvis("⛔ " + res.message + (detail ? "\n" + detail : ""));
  } else {
    ajouterAvis(res.message || "Reponse inattendue.");
  }
  await chargerConversations();
}

// --- branchements -------------------------------------------------------
$("#formulaire").addEventListener("submit", (e) => {
  e.preventDefault();
  const texte = saisie.value.trim();
  if (!texte) return;
  saisie.value = "";
  saisie.style.height = "auto";
  envoyer(texte);
});

// Entree = envoyer, Maj+Entree = nouvelle ligne ; la zone grandit avec le texte.
saisie.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("#formulaire").requestSubmit();
  }
});
saisie.addEventListener("input", () => {
  saisie.style.height = "auto";
  saisie.style.height = Math.min(saisie.scrollHeight, 200) + "px";
});

$("#btn-nouvelle").addEventListener("click", nouvelleConversation);

// Depot de document
$("#btn-doc").addEventListener("click", () => $("#fichier-doc").click());
$("#fichier-doc").addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (f) deposerDocument(f);
  e.target.value = ""; // permet de re-deposer le meme fichier
});

// --- demarrage ----------------------------------------------------------
chargerConversations();
chargerDocuments();
