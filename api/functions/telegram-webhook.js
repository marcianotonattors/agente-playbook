/**
 * Vercel Serverless Function — Telegram Webhook
 * Agente do Playbook da Coordenação BIM com RAG sobre Knowledge Base
 */

import Anthropic from "@anthropic-ai/sdk";
import { createClient } from "@supabase/supabase-js";
import OpenAI from "openai";

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_KEY
);

const TELEGRAM_API = `https://api.telegram.org/bot${process.env.TELEGRAM_BOT_TOKEN}`;
const EMBEDDING_MODEL = "text-embedding-3-small";
const CLAUDE_MODEL = "claude-sonnet-4-6";
const RAG_MATCH_COUNT = 5;
const RAG_MIN_SIMILARITY = 0.7;

// ---------------------------------------------------------------------------
// Embeddings
// ---------------------------------------------------------------------------

async function generateEmbedding(text) {
  const response = await openai.embeddings.create({
    model: EMBEDDING_MODEL,
    input: text,
    dimensions: 1536,
  });
  return response.data[0].embedding;
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

Responda com base nos trechos de referência abaixo. Se a resposta estiver nos trechos, use-os como base principal. Trechos marcados como "tabela" contêm dados estruturados — interprete-os com precisão. Trechos marcados como "descrição de imagem/fluxograma" são descrições técnicas de elementos visuais dos documentos — use-os como se você estivesse explicando o diagrama original.

Se não houver trecho suficiente, use seu conhecimento técnico geral mas indique que é um complemento não coberto pelos materiais do curso.

Quando citar algo específico, use o formato: (Fonte: Nome do Documento, Seção X).`;

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
    max_tokens: 1024,
    system: systemPrompt,
    messages: conversationHistory,
  });
  return response.content[0].text;
}

// ---------------------------------------------------------------------------
// Gerenciamento de histórico de conversa (em memória por sessão)
// Em produção, armazenar no Supabase por chat_id
// ---------------------------------------------------------------------------

const conversationCache = new Map();
const MAX_HISTORY_MESSAGES = 20;

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
  // Mantém janela deslizante
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
  // 1. Gerar embedding da pergunta
  const queryEmbedding = await generateEmbedding(userMessage);

  // 2. Buscar chunks relevantes
  const chunks = await searchChunks(queryEmbedding);

  // 3. Montar contexto e system prompt
  const context = buildContext(chunks);
  const systemPrompt = buildSystemPrompt(context);

  // 4. Histórico de conversa
  const history = getHistory(chatId);
  const messages = [...history, { role: "user", content: userMessage }];

  // 5. Chamar Claude
  const reply = await callClaude(systemPrompt, messages);

  // 6. Atualizar histórico
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

  const body = req.body;

  // Ignora atualizações sem mensagem de texto
  const message = body?.message;
  if (!message?.text) {
    return res.status(200).json({ ok: true });
  }

  const chatId = message.chat.id;
  const userMessage = message.text.trim();

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
