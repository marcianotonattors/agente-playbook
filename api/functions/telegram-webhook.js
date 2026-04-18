/**
 * Vercel Serverless Function — Telegram Webhook
 * Agente do Playbook da Coordenação BIM com RAG sobre Knowledge Base
 */

import Anthropic from "@anthropic-ai/sdk";
import { createClient } from "@supabase/supabase-js";
import { createHmac } from "crypto";

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_KEY
);

const TELEGRAM_API = `https://api.telegram.org/bot${process.env.TELEGRAM_BOT_TOKEN}`;
const EMBEDDING_MODEL = "voyage-3";
const CLAUDE_MODEL = "claude-sonnet-4-6";
const RAG_MATCH_COUNT = 3;
const RAG_MIN_SIMILARITY = 0.5;
const MAX_MESSAGE_LENGTH = 2000;

// ---------------------------------------------------------------------------
// Validação do webhook do Telegram
// ---------------------------------------------------------------------------

function validateTelegramRequest(req) {
  const secret = process.env.TELEGRAM_WEBHOOK_SECRET;
  if (!secret) return true; // se não configurado, não bloqueia (compatibilidade)

  const token = req.headers["x-telegram-bot-api-secret-token"];
  if (!token) return false;

  // Comparação segura contra timing attacks
  const expected = createHmac("sha256", "WebAppData")
    .update(secret)
    .digest("hex");
  const provided = createHmac("sha256", "WebAppData")
    .update(token)
    .digest("hex");

  return expected === provided;
}

// ---------------------------------------------------------------------------
// Rate limiting em memória (por chat_id)
// ---------------------------------------------------------------------------

const rateLimitMap = new Map();
const RATE_LIMIT_WINDOW_MS = 60_000; // 1 minuto
const RATE_LIMIT_MAX_REQUESTS = 10;

function isRateLimited(chatId) {
  const key = String(chatId);
  const now = Date.now();
  const entry = rateLimitMap.get(key) || { count: 0, windowStart: now };

  if (now - entry.windowStart > RATE_LIMIT_WINDOW_MS) {
    entry.count = 1;
    entry.windowStart = now;
  } else {
    entry.count += 1;
  }

  rateLimitMap.set(key, entry);
  return entry.count > RATE_LIMIT_MAX_REQUESTS;
}

// ---------------------------------------------------------------------------
// Embeddings
// ---------------------------------------------------------------------------

async function generateEmbedding(text) {
  const response = await fetch("https://api.voyageai.com/v1/embeddings", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${process.env.VOYAGE_API_KEY}`,
    },
    body: JSON.stringify({ input: [text], model: EMBEDDING_MODEL }),
  });
  const data = await response.json();
  return data.data[0].embedding;
}

// ---------------------------------------------------------------------------
// Busca vetorial no Supabase
// ---------------------------------------------------------------------------

async function searchChunks(queryEmbedding) {
  const { data, error } = await supabase.rpc("search_chunks", {
    query_embedding: queryEmbedding,
    match_count: RAG_MATCH_COUNT,
    min_similarity: RAG_MIN_SIMILARITY,
  });
  if (error) {
    console.error("Erro na busca vetorial:", error);
    return [];
  }
  return data || [];
}

// ---------------------------------------------------------------------------
// Montagem do contexto RAG
// ---------------------------------------------------------------------------

function buildContext(chunks) {
  if (!chunks.length) return null;

  return chunks
    .map((c) => {
      const label = `[${c.source_name}${c.section ? " — " + c.section : ""}]`;
      let typeNote = "";
      if (c.chunk_type === "image_description") {
        typeNote = "(descrição de imagem/fluxograma)\n";
      } else if (c.chunk_type === "table") {
        typeNote = "(tabela)\n";
      }
      return `${label}\n${typeNote}${c.content}`;
    })
    .join("\n\n---\n\n");
}

// ---------------------------------------------------------------------------
// System prompt
// ---------------------------------------------------------------------------

function buildSystemPrompt(context) {
  const base = `Você é o assistente do Playbook da Coordenação BIM, desenvolvido por Marciano Tonatto.

Antes de responder, avalie se a pergunta do aluno é vaga ou depende de contexto que você não tem. Se sim, faça no máximo 2 perguntas curtas e diretas para entender melhor a situação dele — como o software que está usando, em qual etapa do processo está, ou qual o problema específico. Só responda de forma completa depois de ter contexto suficiente ou se a pergunta já for clara.

Quando a pergunta for clara, responda com base nos trechos de referência abaixo. Se a resposta estiver nos trechos, use-os como base principal. Trechos marcados como "tabela" contêm dados estruturados — interprete-os com precisão. Trechos marcados como "descrição de imagem/fluxograma" são descrições técnicas de elementos visuais dos documentos — use-os como se você estivesse explicando o diagrama original.

Se não houver trecho suficiente, use seu conhecimento técnico geral mas indique que é um complemento não coberto pelos materiais do curso.

Quando citar algo específico, use o formato: (Fonte: Nome do Documento, Seção X).

Seja extremamente conciso. Máximo 3 pontos por seção. Sem introduções, sem conclusões, sem exemplos extras. Vá direto ao ponto técnico.

Nunca use tabelas Markdown (| col | col |) — o Telegram não as renderiza. No lugar, use listas com marcadores ou formato "• Item → Equivalente".

FORMATAÇÃO OBRIGATÓRIA: sempre numere as seções principais com 1., 2., 3. e use *negrito* para termos técnicos. Exemplo: "*1. Requisitos de Informação*" como título de seção. Sublistas usam a), b), c). Isso é obrigatório em todas as respostas.

Não use emojis nas respostas. Reserve-os apenas para situações muito específicas de ironia ou humor pontual.`;

  if (!context) {
    return (
      base +
      "\n\n[Nenhum trecho relevante encontrado na base de conhecimento para esta pergunta.]"
    );
  }

  return `${base}\n\n--- TRECHOS DE REFERÊNCIA ---\n${context}\n--- FIM DOS TRECHOS ---`;
}

// ---------------------------------------------------------------------------
// Chamada ao Claude
// ---------------------------------------------------------------------------

async function callClaude(systemPrompt, conversationHistory) {
  const response = await anthropic.messages.create({
    model: CLAUDE_MODEL,
    max_tokens: 500,
    system: systemPrompt,
    messages: conversationHistory,
  });
  return response.content[0].text;
}

// ---------------------------------------------------------------------------
// Gerenciamento de histórico de conversa (em memória por sessão)
// ---------------------------------------------------------------------------

const conversationCache = new Map();
const MAX_HISTORY_MESSAGES = 6;

function getHistory(chatId) {
  return conversationCache.get(String(chatId)) || [];
}

function updateHistory(chatId, userMessage, assistantReply) {
  const key = String(chatId);
  const history = conversationCache.get(key) || [];
  history.push(
    { role: "user", content: userMessage },
    { role: "assistant", content: assistantReply }
  );
  if (history.length > MAX_HISTORY_MESSAGES) {
    history.splice(0, history.length - MAX_HISTORY_MESSAGES);
  }
  conversationCache.set(key, history);
}

// ---------------------------------------------------------------------------
// Envio de mensagem para o Telegram
// ---------------------------------------------------------------------------

async function sendTelegramMessage(chatId, text) {
  await fetch(`${TELEGRAM_API}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text,
      parse_mode: "Markdown",
    }),
  });
}

// ---------------------------------------------------------------------------
// Handler principal da mensagem
// ---------------------------------------------------------------------------

async function handleMessage(chatId, userMessage) {
  const queryEmbedding = await generateEmbedding(userMessage);
  const chunks = await searchChunks(queryEmbedding);
  const context = buildContext(chunks);
  const systemPrompt = buildSystemPrompt(context);
  const history = getHistory(chatId);
  const messages = [...history, { role: "user", content: userMessage }];
  const reply = await callClaude(systemPrompt, messages);
  updateHistory(chatId, userMessage, reply);
  return reply;
}

// ---------------------------------------------------------------------------
// Vercel handler
// ---------------------------------------------------------------------------

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  if (!validateTelegramRequest(req)) {
    return res.status(401).json({ error: "Unauthorized" });
  }

  const body = req.body;
  const message = body?.message;
  if (!message?.text) {
    return res.status(200).json({ ok: true });
  }

  const chatId = message.chat.id;
  const userMessage = message.text.trim().slice(0, MAX_MESSAGE_LENGTH);

  if (isRateLimited(chatId)) {
    await sendTelegramMessage(
      chatId,
      "Muitas mensagens em pouco tempo. Aguarde um momento antes de continuar."
    );
    return res.status(200).json({ ok: true });
  }

  try {
    const reply = await handleMessage(chatId, userMessage);
    await sendTelegramMessage(chatId, reply);
  } catch (err) {
    console.error("Erro ao processar mensagem:", err);
    await sendTelegramMessage(
      chatId,
      "Desculpe, ocorreu um erro ao processar sua pergunta. Tente novamente em instantes."
    );
  }

  return res.status(200).json({ ok: true });
}
