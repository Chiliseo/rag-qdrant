import {QdrantClient} from '@qdrant/js-client-rest';
import fs from 'fs';
import yaml from 'js-yaml';
import path from 'path';
import prompt from 'prompt';

const QDRANT_URL = 'http://127.0.0.1:6333';
const client = new QdrantClient({url: QDRANT_URL});
const MIN_PART = 3;
const COLLECTION_NAME = 'articles';

 async function createCollection(): Promise<boolean> {
  const exists = await client.collectionExists(COLLECTION_NAME);
  if (exists) {
    return true;
  }

    return client.createCollection(COLLECTION_NAME, {
        vectors: {
            size: 1024,
            distance: 'Cosine',
        },
    });
}


function extractMetadataFromMd(file: string) {
    const content = fs.readFileSync(file, 'utf8');

    const parts = content.split("---");
    if (parts.length < MIN_PART) {
        return {};
    }

    const rawMetadata = parts[1];``
    const articleContent = parts.slice(2).join("---").trim();

    let metadata: Record<string, unknown>;
    try {
        metadata = yaml.load(rawMetadata ?? '') as Record<string, unknown>;
    } catch (error) {
        console.error(`Error parsing YAML metadata: ${error}`);
        return {};
    }

    return {
        metadata,
        articleContent,
    };
}


function createChunks(articleContent: string) {
    const chunks = articleContent.split("\n\n");
    return chunks;
}


function cleanArticleContent(articleContent: string) {
    const cleanedContent = articleContent.replace(/^#+ /, '')
    .replace(/<[^>]+>/g, '')
    .replace(/^\n+/, '')
    .replace(/\n+$/, '')
    .trim();
    return cleanedContent;
}

async function generate_response(prompt: string) {
    const response = await fetch("http://localhost:11434/api/generate", {
        method: "POST",
        body: JSON.stringify({
            model: "gemma3:1b",
            prompt: prompt,
            options: {
              num_ctx: 10000,
            },
            stream: true,
        }),

    });
    if (!response.body) {
        throw new Error("Response body is null");
    }

    return response.body.pipeThrough(new TextDecoderStream()).getReader()
}


async function generate_embeddings(text: string) {
  const response = await fetch("http://localhost:11434/api/embed", {
    method: "POST",
    body: JSON.stringify({
      model: "mxbai-embed-large",
      input: text,
    }),
  });

  const data = await response.json();
  if (data.embeddings.length > 0) {
    return data.embeddings[0];
  }
  return null;
}

async function store_article(metadata: any, chunks: string[]) {
  for (const chunk of chunks) {
    const embedding = await generate_embeddings(chunk);
    if (!embedding) {
      continue;
    }
    await client.upsert(COLLECTION_NAME, {
      wait: true,
      points: [{ id: chunk, vector: embedding, payload: metadata }],
    });
  }

}

async function embed_prompt(prompt: string) {
  const response = await fetch("http://localhost:11434/api/embed", {
    method: "POST",
    body: JSON.stringify({
      model: "mxbai-embed-large",
      input: prompt,
    }),
  });
  const data = await response.json();
  return data.embeddings[0];
}


async function main() {
  await createCollection();
  const article_files = fs.readdirSync("./../articles");
  for (const article_file of article_files) {
    const file_path = path.join("./../articles", article_file);
    const { metadata, articleContent } = extractMetadataFromMd(file_path);
    if (!metadata || !articleContent) {
      continue;
    }
    const chunks = createChunks(articleContent);
    await store_article(metadata, chunks);

    metadata["slug"] = article_file.replace(".md", "");
    if (!metadata["title"]) {
      metadata["title"] = article_file.replace(".md", "").replace(
        "_", " ").replace("-", " ");
    }

    const lines = articleContent.split("\n");
    for (const line of lines) {
      if (line.trim().length > 10 && !line.startsWith("[") && !line.startsWith("Home")) {
        metadata["title"] = line.trim().slice(0, 100);
        break;
      }
    }
    // await store_article(metadata, chunks);
  }

  const input = await prompt.get({
    properties: {
      prompt: {
        description: "Enter a prompt",
        type: "string",
      },
    },
  });
  console.log('\n');
  console.log('Searching for relevant passages...');
  const adjusted_prompt = `Represent this sentence for searching relevant: ${input.prompt}`;

  const response  = await embed_prompt(adjusted_prompt);

  const results = await client.query(COLLECTION_NAME, {
    query: response,
    with_payload: true,
    limit: 10,
  });


  const relevant_passages = results.points.map((point) => {
    return `- Article Title: ${point.payload?.title} -- Article Slug: ${point.payload?.slug} -- Article Content: ${point.payload?.content}`;
  }).join("\n");

  const augmented_prompt = `
    The following are relevant passages:
    <retrieved-data>
    ${relevant_passages}
    </retrieved-data>
    Here's the original user prompt, answer with help of the retrieved passages:
    <user-prompt>
    ${input.prompt}
    </user-prompt>
  `;

  const responseGenerated = await generate_response(augmented_prompt);
  const reader = await responseGenerated;
  let fullResponse = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    const { response } = JSON.parse(value);
    fullResponse += response;
    process.stdout.write(response);
  }
  console.log('\n');
}

main();
