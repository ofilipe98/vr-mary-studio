"""Reproducible synthetic evaluation, using frozen labels and two real CPU models.

Run --freeze once, then --evaluate. Evaluation never downloads model files.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

TOPICS = [
    ("Estorno no caixa", "Para desfazer uma venda já encerrada, localize o cupom e solicite o cancelamento ao supervisor.", "O cliente desistiu depois de pagar. Como volto atrás?"),
    ("Sangria do PDV", "A retirada de numerário do caixa deve ser registrada como sangria, com valor e operador responsável.", "Preciso tirar dinheiro da gaveta durante o expediente."),
    ("Suprimento de troco", "Registre suprimento para adicionar numerário ao caixa antes de iniciar as vendas.", "Faltam moedas para devolver ao comprador; como abastecer o caixa?"),
    ("Fechamento cego", "Na conferência cega, o operador informa a contagem sem consultar o saldo esperado do sistema.", "Quero que o funcionário conte as notas sem saber quanto deveria ter."),
    ("Venda suspensa", "Suspenda o cupom aberto para atender outro comprador e recupere a venda suspensa depois.", "Uma pessoa esqueceu a carteira e preciso atender a próxima sem perder os itens."),
    ("Falha de comunicação TEF", "Quando a autorização eletrônica não retorna, consulte o estado da transação antes de tentar nova cobrança.", "O cartão ficou processando; posso passar novamente sem cobrar duas vezes?"),
    ("Devolução parcial", "Selecione apenas os itens devolvidos e informe as quantidades correspondentes na operação de devolução.", "O comprador trouxe de volta só duas unidades da compra inteira."),
    ("Conferência de recebimento", "Compare os volumes e as quantidades entregues com o pedido de compra antes de aceitar a mercadoria.", "Chegou o caminhão do fornecedor; como descobrir se veio tudo certo?"),
    ("Inventário rotativo", "A contagem periódica por grupos permite conferir parte do estoque sem paralisar toda a loja.", "Quero contar pequenas partes das mercadorias a cada dia sem fechar a operação."),
    ("Transferência entre lojas", "Registre a saída na unidade de origem e a entrada na unidade de destino para movimentar estoque entre filiais.", "Como mando produtos de uma unidade para outra mantendo os saldos corretos?"),
    ("Perda por validade", "Mercadoria vencida deve ser retirada do saldo disponível por lançamento de perda com o motivo validade.", "Os iogurtes passaram da data e não podem mais ser vendidos; como baixar?"),
    ("Ruptura de estoque", "Acompanhe produtos sem saldo disponível e priorize sua reposição para evitar indisponibilidade na gôndola.", "As prateleiras estão vazias em alguns itens; como achar o que precisa repor?"),
    ("Conciliação bancária", "Associe cada movimento do extrato à baixa financeira correspondente e investigue diferenças de valor.", "O que saiu da conta do banco não bate com os pagamentos registrados."),
    ("Pagamento em duplicidade", "Verifique as baixas do título e o extrato antes de estornar o pagamento lançado mais de uma vez.", "Paguei a mesma conta duas vezes no sistema; como corrigir?"),
    ("Renegociação de dívida", "Agrupe títulos em aberto e gere novas parcelas conforme o acordo, preservando o histórico original.", "O devedor pediu para dividir o que está atrasado em prestações novas."),
    ("Desconto por antecipação", "Informe o abatimento negociado ao liquidar um título antes de seu vencimento.", "O fornecedor cobra menos se eu quitar hoje em vez de esperar a data."),
    ("Juros de atraso", "No recebimento após o vencimento, aplique os encargos previstos e registre separadamente principal e juros.", "A pessoa pagou depois do prazo; onde entra o valor a mais?"),
    ("Fluxo de caixa projetado", "A projeção reúne recebimentos e pagamentos futuros por data para antecipar necessidades de saldo.", "Como saber se vai faltar dinheiro na semana que vem?"),
    ("Rejeição de destinatário", "Confira CPF ou CNPJ e a situação cadastral do destinatário antes de retransmitir a nota rejeitada.", "O documento fiscal não foi aceito porque os dados do comprador estão errados."),
    ("Carta de correção", "Use carta de correção apenas para informações permitidas, preservando os dados fiscais que exigem cancelamento.", "Escrevi uma observação errada numa nota autorizada; como retificar o texto?"),
    ("Inutilização de numeração", "Justifique os números fiscais que não foram utilizados para regularizar a quebra da sequência.", "Ficou um buraco entre os números das notas emitidas."),
    ("Contingência fiscal", "Durante indisponibilidade do autorizador, use a modalidade de contingência habilitada e transmita depois.", "A internet caiu e a loja precisa continuar emitindo cupons."),
    ("Importação de XML", "Carregue o arquivo eletrônico do fornecedor e confira os dados fiscais antes de confirmar a entrada.", "Recebi a nota por arquivo e não quero digitar todos os produtos."),
    ("Apuração de imposto", "Revise os documentos do período e totalize os débitos e créditos antes de encerrar a competência fiscal.", "Onde descubro quanto de tributo ficou para recolher no mês?"),
    ("Etiqueta de preço", "Gere etiquetas a partir dos preços vigentes e substitua as identificações desatualizadas da gôndola.", "O valor na prateleira é antigo; preciso imprimir os novos cartazes pequenos."),
    ("Promoção programada", "Defina início e término da oferta para que o preço promocional entre em vigor automaticamente.", "Quero que o desconto comece amanhã cedo e acabe no domingo."),
    ("Preço por quantidade", "Configure faixas de quantidade para aplicar valores diferenciados conforme o volume comprado.", "Se o cliente levar três pacotes, cada um deve custar menos."),
    ("Bloqueio de desconto", "Limite a redução permitida por perfil e exija autorização quando o operador ultrapassar o percentual.", "Os caixas estão abatendo demais; quero pedir senha do gerente acima do limite."),
    ("Margem de contribuição", "Subtraia custos e despesas variáveis da receita para avaliar quanto cada produto contribui para o resultado.", "Qual item deixa mais dinheiro depois dos gastos ligados à venda?"),
    ("Atualização de custo", "Recalcule o custo do produto a partir das entradas e dos componentes configurados na compra.", "A mercadoria ficou mais cara no fornecedor; como refletir isso no cadastro?"),
    ("Cadastro de embalagem", "Relacione o código da caixa à unidade de venda e ao fator de conversão da embalagem.", "Compro um fardo com doze, mas vendo cada unidade separadamente."),
    ("Código de barras duplicado", "Remova a associação indevida quando o mesmo identificador estiver vinculado a produtos diferentes.", "O leitor está trazendo o produto errado porque dois itens têm o mesmo código."),
    ("Produto pesável", "Configure a identificação de balança e a interpretação do peso ou valor contido na etiqueta.", "Como o caixa entende quantos gramas tem o queijo embalado?"),
    ("Lote e rastreabilidade", "Registre lote e origem para localizar as entradas e saídas de uma remessa específica.", "O fabricante recolheu uma remessa; preciso descobrir por onde ela passou."),
    ("Curva ABC", "Ordene os itens por participação no faturamento para identificar os produtos de maior importância comercial.", "Quais poucos produtos respondem pela maior parte do que vendemos?"),
    ("Pedido mínimo", "Considere embalagem e quantidade mínima exigida pelo fornecedor ao montar a sugestão de compra.", "O distribuidor só entrega acima de um volume; como evitar pedidos pequenos?"),
    ("Permissão por perfil", "Associe funções a perfis de acesso e atribua o perfil adequado a cada usuário.", "Quero que funcionários diferentes vejam apenas as telas de que precisam."),
    ("Auditoria de alterações", "Consulte o histórico de modificações para identificar autor, horário e valores anteriores do registro.", "Alguém mudou um dado e preciso saber quem foi e o que havia antes."),
    ("Sessão bloqueada", "Encerre a sessão anterior ou solicite o desbloqueio administrativo quando o usuário permanecer conectado.", "Fechei o programa de repente e agora diz que já estou usando em outro lugar."),
    ("Restauração de cópia", "Valide a cópia de segurança e restaure em ambiente separado antes de substituir uma base operacional.", "Perdi os dados; como recuperar o que foi salvo sem estragar a base atual?"),
    ("Exportação de relatório", "Escolha o formato de planilha para analisar os registros do relatório em um editor externo.", "Preciso levar essa listagem para mexer nas colunas fora do sistema."),
    ("Agendamento de rotina", "Cadastre horário e periodicidade para executar o processamento sem intervenção manual recorrente.", "Quero que essa tarefa rode sozinha toda madrugada."),
    ("Integração pendente", "Confira a fila de mensagens e reenvie os registros que falharam após corrigir a causa do erro.", "As alterações de uma loja ainda não chegaram à outra; onde vejo o que ficou parado?"),
    ("Sincronização de relógio", "Mantenha data e hora alinhadas entre estações e servidor para evitar divergências nos registros.", "Os horários dos comprovantes saem diferentes em cada computador."),
    ("Impressora sem papel", "Reponha a bobina e confirme o estado da impressão antes de solicitar outra via do comprovante.", "O papel acabou no meio do recibo; preciso entregar uma cópia legível."),
    ("Separação de encomenda", "Reserve as quantidades do pedido e confira os itens durante a preparação para retirada.", "O cliente vai buscar mais tarde e não posso vender os produtos que ele escolheu."),
    ("Entrega agendada", "Registre endereço e janela de atendimento para organizar o roteiro de distribuição dos pedidos.", "Preciso combinar em que período a compra chegará na casa da pessoa."),
    ("Comissão de vendedor", "Calcule a remuneração variável conforme vendas elegíveis e percentuais do acordo comercial.", "Quanto cada funcionário deve receber a mais pelo que conseguiu vender?"),
]


def freeze(path):
    documents, queries = [], []
    for i, (title, text, query) in enumerate(TOPICS):
        source = ('wiki', 'kb', 'schema')[i % 3]
        origin = {'wiki':'vrwiki','kb':'movidesk','schema':'local'}[source]
        doc = dict(id=i+1, source=source, source_id=f'case-{i:02}', source_origin=origin, title=title,
                   markdown=text, module='Multimodulo', product='', revision='r2', status='active', url=f'https://fixture.invalid/{i}', local_path='')
        documents.append(doc)
        # A previous version is a hard negative in the same vector neighborhood.
        documents.append({**doc, 'id':i+101, 'source_id':f'old-{i:02}', 'revision':'r1', 'markdown':text+' Procedimento histórico revogado; versão anterior.'})
        queries.append(dict(id=f'q{i:02}', text=query, relevant=[f'{source}:case-{i:02}'], split='development' if i<12 else 'evaluation', kind='paraphrase', revision='r2'))
    for i in range(8):
        doc = documents[2*i]
        identifier = f'VRX_{9100+i}'
        doc['markdown'] += f' Identificador exato: {identifier}.'
        queries.append(dict(id=f'exact{i}',text=identifier,relevant=[f"{doc['source']}:{doc['source_id']}"],split='evaluation',kind='exact',revision='r2'))
    for i,text in enumerate(['orbital lunar docking','receita de bolo de cenoura','previsão meteorológica de Marte','cirurgia de catarata','dinossauros do jurássico','cotação de criptomoedas']):
        queries.append(dict(id=f'none{i}',text=text,relevant=[],split='evaluation',kind='no_answer',revision='r2'))
    data = {'provenance':'Synthetic fixtures; not ERP product instructions or real customer records.',
            'policy':{'rrf_k':60,'warm_p95_ms':1500,'peak_rss_mb':1500,'paraphrase_gain_pp':5,'max_mrr_drop':.02,'seed':0},
            'documents':documents,'queries':queries}
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def evaluate(corpus, root, output):
    from vrsoft_extractor.mary.db import MaryDatabase
    from vrsoft_extractor.mary.models import KnowledgeDocument
    from vrsoft_extractor.mary.retrieval.local_neural import LocalOnnxEmbedding
    from vrsoft_extractor.mary.retrieval.generations import GenerationSemanticIndex
    from vrsoft_extractor.mary.retrieval.hybrid_search import reciprocal_rank_fusion
    import psutil
    data=json.loads(corpus.read_text(encoding='utf-8'))
    db=MaryDatabase(root/'indice'/'benchmark.sqlite',root=root)
    for row in data['documents']:
        values={k:v for k,v in row.items() if k!='id'}
        values['content_hash']=hashlib.sha256(row['markdown'].encode()).hexdigest()
        values['review_status']='approved'
        db.upsert_document(KnowledgeDocument(**values))
    report={'corpus_sha256':hashlib.sha256(corpus.read_bytes()).hexdigest(),'hardware':{'platform':platform.platform(),'cpu':platform.processor(),'cores':psutil.cpu_count(),'ram_mb':psutil.virtual_memory().total/2**20},'policy':data['policy'],'documents':len(data['documents']),'queries':len(data['queries']),'models':{}}
    for model in ('e5-small','minilm'):
        started=time.perf_counter()
        backend=LocalOnnxEmbedding(root,model)
        cold_ms=(time.perf_counter()-started)*1000
        index=GenerationSemanticIndex(root/'indice'/f'benchmark-{model}.sqlite',backend)
        build=index.rebuild(data['documents'])
        results=[]
        for q in data['queries']:
            with db.connect() as conn:
                allowed={f"{r['source']}:{r['source_id']}" for r in conn.execute("SELECT source,source_id FROM documents WHERE revision=?",(q['revision'],))}
            started=time.perf_counter()
            lexical=[f"{r['source']}:{r['source_id']}" for r in db.search(q['text'],limit=200) if f"{r['source']}:{r['source_id']}" in allowed][:10]
            lexical_ms=(time.perf_counter()-started)*1000
            started=time.perf_counter()
            semantic=[r['doc_id'] for r in index.search(q['text'],limit=10,revision=q['revision'])]
            hybrid=lexical if q['kind']=='exact' else [key for key,_ in reciprocal_rank_fusion(lexical,semantic)][:10]
            elapsed=(time.perf_counter()-started)*1000+lexical_ms
            results.append({**q,'lexical':lexical,'semantic':semantic,'hybrid':hybrid,'milliseconds':elapsed})
        def metrics(rows,field):
            labelled=[q for q in rows if q['relevant']]
            return {'recall10':statistics.mean(len(set(q[field])&set(q['relevant']))/len(q['relevant']) for q in labelled),
                    'mrr':statistics.mean(next((1/(i+1) for i,k in enumerate(q[field]) if k in q['relevant']),0) for q in labelled)}
        evaluation=[q for q in results if q['split']=='evaluation']
        paraphrases=[q for q in evaluation if q['kind']=='paraphrase']
        latencies=sorted(q['milliseconds'] for q in evaluation)
        entry={'build':build,'model':backend.model_name,'cold_load_ms':cold_ms,'warm_p50_ms':statistics.median(latencies),'warm_p95_ms':latencies[int(.95*(len(latencies)-1))],
               'peak_rss_mb':psutil.Process().memory_info().peak_wset/2**20 if hasattr(psutil.Process().memory_info(),'peak_wset') else psutil.Process().memory_info().rss/2**20,
               'index_bytes':index.db_path.stat().st_size,'evaluation':{field:metrics(evaluation,field) for field in ('lexical','semantic','hybrid')},
               'paraphrases':{field:metrics(paraphrases,field) for field in ('lexical','semantic','hybrid')},
               'development':{field:metrics([q for q in results if q['split']=='development'],field) for field in ('lexical','semantic','hybrid')},
               'exact_preserved':all(q['hybrid']==q['lexical'] and bool(set(q['lexical'])&set(q['relevant'])) for q in evaluation if q['kind']=='exact'),
               'isolation_passed':all(not any(':old-' in key for key in q['hybrid']) for q in results),
               'results':results}
        entry['promotion_passed']=(entry['exact_preserved'] and entry['isolation_passed'] and entry['paraphrases']['hybrid']['recall10']-entry['paraphrases']['lexical']['recall10']>=.05 and entry['evaluation']['hybrid']['mrr']>=entry['evaluation']['lexical']['mrr']-.02 and entry['warm_p95_ms']<=data['policy']['warm_p95_ms'] and entry['peak_rss_mb']<=data['policy']['peak_rss_mb'])
        report['models'][model]=entry
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(model, {k:v for k,v in entry.items() if k!='results'},flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--freeze',action='store_true')
    parser.add_argument('--corpus',type=Path,default=Path('tests/fixtures/v2_retrieval_corpus.json'))
    parser.add_argument('--root',type=Path,default=Path('reports/v2/conclusao/model-lab'))
    parser.add_argument('--output',type=Path,default=Path('reports/v2/conclusao/retrieval-benchmark.json'))
    args=parser.parse_args()
    if args.freeze: freeze(args.corpus)
    else: evaluate(args.corpus,args.root.resolve(),args.output)
