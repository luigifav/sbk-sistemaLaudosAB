"use strict";
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber
} = require("docx");

// ── Paleta SBK extraída do documento modelo ──
const VERDE_ESC  = "1F3A3A";   // cabeçalho, rótulos e títulos
const VERDE_MED  = "2A7A6F";   // cabeçalhos de colunas nas tabelas
const VERDE_VIB  = "01B2AA";   // divisores, destaques, processo no header
const FUNDO_VERDE= "E6F7F6";   // fundo do resultado favorável
const FUNDO_VERM = "FEF2F2";   // fundo do resultado desfavorável
const CINZA_LIN  = "F5F6F8";   // fundo dos rótulos
const TEXTO      = "0F2F3A";   // texto principal
const TEXTO_CL   = "6B7280";   // texto secundário (footer, subtítulo header)
const HEADER_CL  = "C8D8D8";   // texto claro do header
const BRANCO     = "FFFFFF";
const VERDE_SIM  = "1A7A5E";
const VERM       = "DC2626";

// ── Dados de exemplo (substituídos pelos dados do banco na integração) ──
const path = require("path");

// Dados: lidos do JSON passado como argumento (produção) ou exemplo fixo (teste local)
var D;
if(process.argv[2] && fs.existsSync(process.argv[2])){
  D = JSON.parse(fs.readFileSync(process.argv[2], "utf-8"));
  D.data_dist     = D.data_dist     || D.dt_inclusao  || "";
  D.autor         = D.autor         || D.nome_cliente  || "";
  D.cpf           = D.cpf           || D.nr_cpf_cnpj   || "";
  D.endereco      = D.endereco      || "";
  D.data_laudo    = D.data_laudo    || new Date().toLocaleDateString("pt-BR");
  D.subsidios_fav = D.subsidios_fav || "";
  D.estrategia    = D.estrategia    || "";
  D.resultado_tipo= D.resultado_tipo|| "";
  D.resumo_causa  = D.resumo_causa  || "";
  D.adv_agressor  = D.adv_agressor  || "";
  if(!D.contratos) D.contratos = [];
  var ckCols = ["ck_bo","ck_analfabeto","ck_terceiros","ck_primeira_tx","ck_biometria_leg",
   "ck_biometria_ok","ck_docs_ok","ck_conta_agi","ck_compras","ck_compras_anormais",
   "ck_ted","ck_saque_cartao","ck_uso_cartao","ck_pagamento_fatura","ck_valor_conta",
   "ck_spc","ck_procuracao","ck_comprov_end","ck_outras_acoes","ck_passagens"];
  ckCols.forEach(function(k){ if(!D[k]) D[k] = ""; });
  var sisCols = ["appsmith_qtd","conductor_qtd","fraud_qtd","ged_qtd",
   "matera_qtd","recupera_qtd","salesforce_qtd","biometria_qtd"];
  sisCols.forEach(function(k){ if(!D[k]) D[k] = "0"; });
} else {
  D = {
    produto:"EMPRESTIMO CONSIGNADO", processo:"5277497-31.2026.8.09.0051",
    data_dist:"04/03/2026", autor:"EUNICIA MOREIRA DA SILVA",
    cpf:"124.202.631-20", endereco:"Rua das Flores, 123, Goiania - GO",
    causa_raiz:"Alegacao de fraude", adv_agressor:"Nao",
    responsavel:"Analista SBK", data_laudo:new Date().toLocaleDateString("pt-BR"),
    subsidios_fav:"Sim", estrategia:"DEFESA",
    resultado_tipo:"SUBSIDIO FAVORAVEL - CONTRATACAO REGULAR",
    resumo_causa:"A autora alega desconhecer a contratacao do emprestimo consignado.",
    contratos:[{nr:"152089389",prod:"Emprestimo Consignado",dt:"12/01/2026",vl:"8.500,00",canal:"Digital"}],
    ck_bo:"Nao", ck_analfabeto:"Nao", ck_terceiros:"Nao", ck_primeira_tx:"Nao",
    ck_biometria_leg:"Sim", ck_biometria_ok:"Sim", ck_docs_ok:"Sim", ck_conta_agi:"Sim",
    ck_compras:"Sim", ck_compras_anormais:"Nao", ck_ted:"Nao", ck_saque_cartao:"N/A",
    ck_uso_cartao:"N/A", ck_pagamento_fatura:"N/A", ck_valor_conta:"Sim", ck_spc:"Nao",
    ck_procuracao:"N/A", ck_comprov_end:"Sim", ck_outras_acoes:"Nao", ck_passagens:"Sim",
    appsmith_qtd:"3", conductor_qtd:"1", fraud_qtd:"0", ged_qtd:"4",
    matera_qtd:"0", recupera_qtd:"0", salesforce_qtd:"2", biometria_qtd:"1",
  };
}


// ── Helpers ──
function bdr(cor, sz) { return { style: BorderStyle.SINGLE, size: sz || 4, color: cor }; }
function bdrs(cor, sz) { var b = bdr(cor, sz); return { top: b, bottom: b, left: b, right: b }; }
function noBdr() { return { style: BorderStyle.NONE, size: 0, color: BRANCO }; }
function noBdrs() { var b = noBdr(); return { top: b, bottom: b, left: b, right: b }; }

function mkCell(txt, opts) {
  opts = opts || {};
  return new TableCell({
    columnSpan: opts.span || 1,
    borders: opts.bordas !== undefined ? opts.bordas : bdrs(VERDE_VIB, 4),
    shading: { fill: opts.fundo || BRANCO, type: ShadingType.CLEAR },
    margins: { top: 80, bottom: 80, left: 140, right: 140 },
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({
      alignment: opts.alin || AlignmentType.LEFT,
      spacing: { before: 0, after: 0 },
      children: [new TextRun({
        text: txt,
        bold: !!opts.bold,
        color: opts.cor || TEXTO,
        font: "Arial",
        size: opts.sz || 19
      })]
    })]
  });
}

// Linha padrão: rótulo cinza | valor branco
function mkRow(label, valor, fundoValor) {
  return new TableRow({ children: [
    mkCell(label, { bold: true, cor: VERDE_ESC, fundo: CINZA_LIN, sz: 19 }),
    mkCell(valor, { cor: TEXTO, fundo: fundoValor || BRANCO, sz: 19 }),
  ]});
}

// Cabeçalho de seção interna da tabela
function mkSecao(txt) {
  return new TableRow({ children: [
    mkCell(txt, { span: 2, bold: true, cor: BRANCO, fundo: VERDE_ESC, sz: 19 })
  ]});
}

// Linha do checklist
function mkCheck(perg, resp) {
  var fav  = resp === "Sim";
  var desf = resp === "Nao";
  return new TableRow({ children: [
    mkCell(perg, { fundo: BRANCO, sz: 18 }),
    mkCell(resp, {
      bold: true,
      cor:   fav ? VERDE_SIM : desf ? VERM : TEXTO,
      fundo: fav ? "F0FDF4" : desf ? FUNDO_VERM : BRANCO,
      alin:  AlignmentType.CENTER,
      sz: 18
    }),
  ]});
}

// Título de seção
function mkTitulo(txt) {
  return new Paragraph({
    spacing: { before: 240, after: 120 },
    children: [new TextRun({ text: txt, bold: true, font: "Arial", size: 22, color: VERDE_ESC })]
  });
}

// Parágrafo de texto
function mkPara(txt, opts) {
  opts = opts || {};
  return new Paragraph({
    spacing: { before: opts.antes || 80, after: opts.depois || 80 },
    alignment: opts.alin !== undefined ? opts.alin : AlignmentType.JUSTIFIED,
    children: [new TextRun({
      text: txt,
      italic: !!opts.italico,
      bold:   !!opts.bold,
      font: "Arial",
      size: opts.sz || 20,
      color: opts.cor || TEXTO
    })]
  });
}

// Divisor com linha na cor verde vibrante
function divisor() {
  return new Paragraph({
    spacing: { before: 120, after: 120 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: VERDE_VIB, space: 1 } },
    children: [new TextRun("")]
  });
}

function vazio() {
  return new Paragraph({ spacing: { before: 40, after: 40 }, children: [new TextRun("")] });
}

// ── Parecer padronizado automático ──
function gerarParecer(d) {
  var paras = [];
  var prod = d.produto.indexOf("CONSIGNADO") !== -1 ? "emprestimo consignado" :
             d.produto.indexOf("CARTAO")     !== -1 ? "cartao consignado"     : "credito pessoal";
  var fav  = d.subsidios_fav === "Sim";

  paras.push(mkPara(
    "Com base na analise dos subsidios levantados junto aos sistemas internos do Agibank, referente ao " +
    prod + " vinculado ao presente processo, os elementos apurados sao " +
    (fav ? "FAVORAVEIS" : "DESFAVORAVEIS") + " ao Agibank.",
    { antes: 100, depois: 80 }
  ));

  var evFav = [];
  if (d.ck_biometria_ok  === "Sim") evFav.push("biometria facial conferida com os documentos da inicial");
  if (d.ck_docs_ok       === "Sim") evFav.push("documentos do autor (RG, CPF e endereco) compativeis com o cadastro do Agibank");
  if (d.ck_conta_agi     === "Sim") evFav.push("cliente com conta ativa no Agibank, evidenciando relacionamento bancario preexistente");
  if (d.ck_primeira_tx   === "Nao") evFav.push("historico de transacoes anteriores com a instituicao");
  if (d.ck_terceiros     === "Nao") evFav.push("valor creditado sem transferencia imediata para terceiros");
  if (d.ck_analfabeto    === "Nao") evFav.push("ausencia de indicios de analfabetismo, interdicao ou doenca grave");

  var evDesf = [];
  if (d.ck_bo            === "Sim") evDesf.push("Boletim de Ocorrencia apresentado pelo autor");
  if (d.ck_analfabeto    === "Sim") evDesf.push("indicios de analfabetismo, interdicao ou doenca grave");
  if (d.ck_terceiros     === "Sim") evDesf.push("valor transferido para terceiros em data proxima ao recebimento");
  if (d.ck_biometria_leg === "Nao") evDesf.push("biometria facial ilegivel no momento da contratacao");
  if (d.ck_biometria_ok  === "Nao") evDesf.push("biometria nao confere com os documentos da inicial");
  if (d.ck_docs_ok       === "Nao") evDesf.push("divergencias entre documentos da inicial e cadastro do Agibank");

  if (evFav.length > 0)
    paras.push(mkPara(
      "Os seguintes elementos corroboram a regularidade da contratacao: " + evFav.join("; ") + ".",
      { antes: 60, depois: 60 }
    ));
  if (evDesf.length > 0)
    paras.push(mkPara(
      "Os seguintes elementos apresentam ressalvas: " + evDesf.join("; ") + ".",
      { antes: 60, depois: 60 }
    ));

  var sis = [];
  if (d.appsmith_qtd   && d.appsmith_qtd   !== "0") sis.push("AppSmith (" + d.appsmith_qtd + " anexos)");
  if (d.conductor_qtd  && d.conductor_qtd  !== "0") sis.push("Conductor (" + d.conductor_qtd + " registros)");
  if (d.ged_qtd        && d.ged_qtd        !== "0") sis.push("GED (" + d.ged_qtd + " documentos)");
  if (d.salesforce_qtd && d.salesforce_qtd !== "0") sis.push("Salesforce (" + d.salesforce_qtd + " registros)");
  if (d.biometria_qtd  && d.biometria_qtd  !== "0") sis.push("Unico Biometria (" + d.biometria_qtd + " registros)");
  if (d.fraud_qtd      && d.fraud_qtd      !== "0") sis.push("Fraud Prevention (" + d.fraud_qtd + " registros)");
  if (d.matera_qtd     && d.matera_qtd     !== "0") sis.push("Matera (" + d.matera_qtd + " registros)");
  if (d.recupera_qtd   && d.recupera_qtd   !== "0") sis.push("Recupera (" + d.recupera_qtd + " registros)");
  if (sis.length > 0)
    paras.push(mkPara(
      "Sistemas consultados para emissao deste parecer: " + sis.join(", ") + ".",
      { antes: 60, depois: 60 }
    ));

  paras.push(mkPara(
    d.estrategia === "DEFESA"
      ? "Diante do exposto, recomenda-se a estrategia de DEFESA, tendo em vista que os subsidios apurados indicam a regularidade da operacao e a ausencia de irregularidades que justifiquem o acolhimento do pedido autoral."
      : "Diante do exposto, recomenda-se a estrategia de ACORDO, uma vez que os subsidios apurados nao sao suficientes para embasar uma defesa consistente, sendo mais adequada a busca por composicao amigavel.",
    { antes: 80, depois: 80 }
  ));
  return paras;
}

// ── Tabelas ──

// 1. Identificação
var tblIdent = new Table({
  width: { size: 9638, type: WidthType.DXA },
  columnWidths: [2800, 6838],
  rows: [
    mkSecao("DADOS DA ACAO JUDICIAL"),
    mkRow("No Processo Judicial", D.processo),
    mkRow("Data de Distribuicao", D.data_dist),
    mkRow("Autor(a)",             D.autor),
    mkRow("CPF",                  D.cpf),
    mkRow("Endereco",             D.endereco),
    mkSecao("CLASSIFICACAO DO PROCESSO"),
    mkRow("Produto Principal",    D.produto),
    mkRow("Causa Raiz",           D.causa_raiz),
    mkRow("Advogado Agressor",    D.adv_agressor),
  ]
});

// 4. Checklist
var tblCheck = new Table({
  width: { size: 9638, type: WidthType.DXA },
  columnWidths: [7638, 2000],
  rows: [
    new TableRow({ children: [
      mkCell("ITEM DE VERIFICACAO",  { bold: true, cor: BRANCO, fundo: VERDE_MED, sz: 19 }),
      mkCell("RESULTADO",            { bold: true, cor: BRANCO, fundo: VERDE_MED, alin: AlignmentType.CENTER, sz: 19 }),
    ]}),
    mkCheck("O autor apresenta Boletim de Ocorrencia? Narrativa confere com a inicial?",       D.ck_bo),
    mkCheck("Autor traz evidencias de analfabetismo, interdicao ou doenca grave?",             D.ck_analfabeto),
    mkCheck("O valor liberado foi transferido para terceiros em data proxima ao recebimento?",  D.ck_terceiros),
    mkCheck("Foi a primeira transacao do cliente com o Agibank?",                               D.ck_primeira_tx),
    mkCheck("A biometria facial coletada na contratacao esta legivel?",                         D.ck_biometria_leg),
    mkCheck("A biometria confere com os documentos apresentados na inicial?",                   D.ck_biometria_ok),
    mkCheck("Os documentos da inicial (RG, CPF, endereco) conferem com o cadastro Agibank?",   D.ck_docs_ok),
    mkCheck("O cliente possui conta ativa no Agibank?",                                         D.ck_conta_agi),
  ]
});

// 5. Sistemas
var sisRows = [new TableRow({ children: [
  mkCell("SISTEMA",               { bold: true, cor: BRANCO, fundo: VERDE_MED, sz: 19 }),
  mkCell("REGISTROS ENCONTRADOS", { bold: true, cor: BRANCO, fundo: VERDE_MED, alin: AlignmentType.CENTER, sz: 19 }),
]})];
[
  { nome: "AppSmith",         qtd: D.appsmith_qtd,   unid: "anexos"     },
  { nome: "Conductor",        qtd: D.conductor_qtd,  unid: "registros"  },
  { nome: "Fraud Prevention", qtd: D.fraud_qtd,      unid: "registros"  },
  { nome: "GED",              qtd: D.ged_qtd,        unid: "documentos" },
  { nome: "Matera",           qtd: D.matera_qtd,     unid: "registros"  },
  { nome: "Recupera",         qtd: D.recupera_qtd,   unid: "registros"  },
  { nome: "Salesforce",       qtd: D.salesforce_qtd, unid: "registros"  },
  { nome: "Unico Biometria",  qtd: D.biometria_qtd,  unid: "registros"  },
].forEach(function(s) {
  var val = (!s.qtd || s.qtd === "0") ? "Nao consultado" : s.qtd + " " + s.unid;
  sisRows.push(new TableRow({ children: [
    mkCell(s.nome, { sz: 19 }),
    mkCell(val,    { alin: AlignmentType.CENTER, sz: 19 }),
  ]}));
});
var tblSistemas = new Table({
  width: { size: 9638, type: WidthType.DXA },
  columnWidths: [4819, 4819],
  rows: sisRows
});

// 6. Resultado final
var fav = D.subsidios_fav === "Sim";
var corBorda  = fav ? VERDE_VIB : VERM;
var corFundo  = fav ? FUNDO_VERDE : FUNDO_VERM;
var resTxt = "Subsidios: " + D.subsidios_fav + "   |   Estrategia: " + D.estrategia + "   |   Resultado: " + D.resultado_tipo;

var tblResultado = new Table({
  width: { size: 9638, type: WidthType.DXA },
  columnWidths: [2800, 6838],
  rows: [
    new TableRow({ children: [
      new TableCell({
        columnSpan: 2,
        borders: bdrs(corBorda, 10),
        shading: { fill: corFundo, type: ShadingType.CLEAR },
        margins: { top: 160, bottom: 160, left: 200, right: 200 },
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: resTxt, bold: true, font: "Arial", size: 21, color: VERDE_ESC })]
        })]
      })
    ]}),
    mkRow("Subsidios Favoraveis", D.subsidios_fav),
    mkRow("Estrategia",           D.estrategia,  fav ? FUNDO_VERDE : FUNDO_VERM),
    mkRow("Resultado",            D.resultado_tipo),
    mkRow("Data do Laudo",        D.data_laudo),
    mkRow("Responsavel",          D.responsavel),
  ]
});

// ── Cabeçalho (verde escuro com processo e data) ──
var headerTbl = new Table({
  width: { size: 9638, type: WidthType.DXA },
  columnWidths: [6200, 3438],
  borders: { top: noBdr(), bottom: noBdr(), left: noBdr(), right: noBdr(), insideH: noBdr(), insideV: noBdr() },
  rows: [new TableRow({ children: [
    new TableCell({
      borders: noBdrs(),
      shading: { fill: VERDE_ESC, type: ShadingType.CLEAR },
      margins: { top: 120, bottom: 120, left: 200, right: 200 },
      verticalAlign: VerticalAlign.CENTER,
      children: [
        new Paragraph({ spacing: { before: 0, after: 0 }, children: [
          new TextRun({ text: "PARECER DE SUBSIDIOS", bold: true, font: "Arial", size: 22, color: BRANCO })
        ]}),
        new Paragraph({ spacing: { before: 0, after: 0 }, children: [
          new TextRun({ text: "Contencioso  -  Analise Pericial", font: "Arial", size: 16, color: HEADER_CL })
        ]}),
      ]
    }),
    new TableCell({
      borders: noBdrs(),
      shading: { fill: VERDE_ESC, type: ShadingType.CLEAR },
      margins: { top: 120, bottom: 120, left: 200, right: 200 },
      verticalAlign: VerticalAlign.CENTER,
      children: [
        new Paragraph({ alignment: AlignmentType.RIGHT, spacing: { before: 0, after: 0 }, children: [
          new TextRun({ text: "Processo: " + D.processo, font: "Arial", size: 16, color: VERDE_VIB })
        ]}),
        new Paragraph({ alignment: AlignmentType.RIGHT, spacing: { before: 0, after: 0 }, children: [
          new TextRun({ text: "Laudo: " + D.data_laudo, font: "Arial", size: 16, color: HEADER_CL })
        ]}),
      ]
    }),
  ]})]
});

// ── Rodapé ──
var footerPara = new Paragraph({
  alignment: AlignmentType.CENTER,
  border: { top: { style: BorderStyle.SINGLE, size: 4, color: VERDE_VIB } },
  spacing: { before: 80 },
  children: [
    new TextRun({ text: "SBK Legal Operations   |   Documento Confidencial   |   Pagina ", font: "Arial", size: 16, color: TEXTO_CL }),
    new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 16, color: TEXTO_CL }),
  ]
});

// ── Montagem do documento ──
var conteudo = [

  // 1. Identificação
  mkTitulo("1. IDENTIFICACAO DO CASO"),
  tblIdent,
  divisor(),

  // 2. Contratos — texto corrido conforme modelo
  mkTitulo("2. CONTRATO(S) VINCULADO(S)"),
];

// Um parágrafo por contrato no formato do modelo
D.contratos.forEach(function(ct) {
  conteudo.push(new Paragraph({
    spacing: { before: 80, after: 80 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: VERDE_VIB, space: 1 } },
    children: [new TextRun({
      text: "Contrato no " + ct.nr + " foi realizado em " + ct.dt + ", produto " + ct.prod + ", valor de R$ " + ct.vl + ", por meio do canal " + ct.canal + ".",
      font: "Arial", size: 20, color: TEXTO
    })]
  }));
});
conteudo.push(vazio());

conteudo = conteudo.concat([

  // 3. Resumo
  mkTitulo("3. RESUMO DA CAUSA"),
  mkPara(D.resumo_causa, { antes: 80, depois: 100 }),
  divisor(),

  // 4. Checklist
  mkTitulo("4. CHECKLIST DE ANALISE"),
  mkPara("Respostas obtidas a partir da analise dos documentos e sistemas disponiveis:", { italico: true, sz: 18, cor: TEXTO_CL, antes: 60, depois: 100 }),
  tblCheck,
  divisor(),

  // 5. Sistemas
  mkTitulo("5. SISTEMAS CONSULTADOS"),
  tblSistemas,
  divisor(),

  // 6. Resultado final
  mkTitulo("6. RESULTADO FINAL"),
  tblResultado,
  vazio(),
]);

// Parecer automático logo abaixo, sem título de seção
gerarParecer(D).forEach(function(p) { conteudo.push(p); });
conteudo.push(vazio());

var doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 20, color: TEXTO } } }
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 },
        margin: { top: 1134, right: 1134, bottom: 1134, left: 1134 }
      }
    },
    headers: { default: new Header({ children: [headerTbl] }) },
    footers: { default: new Footer({ children: [footerPara] }) },
    children: conteudo
  }]
});

Packer.toBuffer(doc).then(function(buf) {
  var outPath = process.argv[3] || "/home/claude/laudo_oficial.docx";
  fs.writeFileSync(outPath, buf);
  console.log("OK");
});
