// Função: fnEGestor
// Lê todos os arquivos de uma pasta de dados/ do GitHub e junta numa tabela só.
// Uso: fnEGestor("financiamento")
// Colunas vl*, qt*, pc*, percentual* e qtd* viram número; códigos ficam como texto.
// A coluna "periodo" vem do nome do arquivo (AAAAMM ou AAAAQn).
(pasta as text) as table =>
let
    Base = EGESTOR_URL_BASE,
    Indice = Lines.FromBinary(Web.Contents(Base, [RelativePath = "_arquivos.txt", Headers = [#"Cache-Control" = "no-cache"]]), null, null, 65001),
    Arquivos = List.Select(Indice, each Text.StartsWith(_, pasta & "/")),
    Ler = (arq as text) as table =>
        let
            Bin = Binary.Decompress(Web.Contents(Base, [RelativePath = arq]), Compression.GZip),
            Csv = Csv.Document(Bin, [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
            Cab = Table.PromoteHeaders(Csv, [PromoteAllScalars = true]),
            ComPeriodo = Table.AddColumn(Cab, "periodo", each Text.BeforeDelimiter(Text.AfterDelimiter(arq, "/"), "."), type text)
        in
            ComPeriodo,
    Junta = Table.Combine(List.Transform(Arquivos, Ler)),
    Numericas = List.Select(Table.ColumnNames(Junta), each
        List.Contains({"vl", "qt", "pc"}, Text.Start(_, 2)) or Text.StartsWith(_, "percentual")),
    Tipos = Table.TransformColumnTypes(Junta, List.Transform(Numericas, each {_, type number}), "en-US"),
    SemErro = Table.ReplaceErrorValues(Tipos, List.Transform(Numericas, each {_, null}))
in
    SemErro
