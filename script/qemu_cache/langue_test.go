// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"testing"
)

// Les tests lisent les messages en français, langue du code source : une
// langue héritée de l'environnement de qui les lance les ferait échouer sur
// une chaîne traduite.
func TestMain(m *testing.M) {
	definirLangue(LangueFr)
	os.Exit(m.Run())
}

// clesT rend le texte de chaque appel T("…") des fichiers du paquet, tests
// exclus, avec sa position. Un argument qui n'est pas un littéral est une
// erreur : le catalogue ne pourrait pas le traduire.
func clesT(t *testing.T) map[string]string {
	t.Helper()
	fichiers, err := filepath.Glob("*.go")
	if err != nil {
		t.Fatal(err)
	}
	fs := token.NewFileSet()
	cles := map[string]string{}
	for _, f := range fichiers {
		if strings.HasSuffix(f, "_test.go") {
			continue
		}
		af, err := parser.ParseFile(fs, f, nil, 0)
		if err != nil {
			t.Fatal(err)
		}
		ast.Inspect(af, func(n ast.Node) bool {
			c, ok := n.(*ast.CallExpr)
			if !ok {
				return true
			}
			id, ok := c.Fun.(*ast.Ident)
			if !ok || id.Name != "T" || len(c.Args) != 1 {
				return true
			}
			texte, ok := litteralT(c.Args[0])
			pos := fs.Position(c.Pos()).String()
			if !ok {
				// Une conversion de valeur connue — T(string(gran)) — se
				// vérifie par son propre test ; tout autre argument non
				// littéral est refusé.
				if conv, estConv := c.Args[0].(*ast.CallExpr); estConv {
					if fn, ok := conv.Fun.(*ast.Ident); ok && fn.Name == "string" {
						return true
					}
				}
				t.Errorf("%s : T() sur un texte non littéral", pos)
				return true
			}
			cles[texte] = pos
			return true
		})
	}
	return cles
}

func litteralT(e ast.Expr) (string, bool) {
	switch v := e.(type) {
	case *ast.BasicLit:
		if v.Kind != token.STRING {
			return "", false
		}
		s, err := strconv.Unquote(v.Value)
		return s, err == nil
	case *ast.BinaryExpr:
		if v.Op != token.ADD {
			return "", false
		}
		a, ok1 := litteralT(v.X)
		b, ok2 := litteralT(v.Y)
		return a + b, ok1 && ok2
	case *ast.ParenExpr:
		return litteralT(v.X)
	}
	return "", false
}

// Un message enveloppé sans traduction sortirait en français dans un binaire
// réglé en anglais, sans que rien ne le signale.
func TestChaqueMessageATraductionAnglaise(t *testing.T) {
	cles := clesT(t)
	if len(cles) < 100 {
		t.Fatalf("%d appels T() trouvés : le contrôle ne lit pas le code", len(cles))
	}
	var manquants []string
	for texte, pos := range cles {
		if _, ok := anglais[texte]; !ok {
			manquants = append(manquants, pos+" "+strconv.Quote(texte))
		}
	}
	sort.Strings(manquants)
	for _, m := range manquants {
		t.Errorf("sans traduction : %s", m)
	}
}

// Une entrée qu'aucun appel n'emploie est un message retiré, ou une clé qui
// ne correspond plus au texte réécrit : sa traduction ne sortirait jamais.
func TestAucuneTraductionOrpheline(t *testing.T) {
	cles := clesT(t)
	// Clés employées par conversion : les granularités affichées.
	for _, g := range []Granularite{ParJour, ParSemaine, ParMois} {
		cles[string(g)] = "granularité"
	}
	var orphelines []string
	for texte := range anglais {
		if _, ok := cles[texte]; !ok {
			orphelines = append(orphelines, strconv.Quote(texte))
		}
	}
	sort.Strings(orphelines)
	for _, o := range orphelines {
		t.Errorf("traduction sans appel : %s", o)
	}
}

var verbeFormat = regexp.MustCompile(`%[-+# 0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[a-zA-Z%]`)

// Une traduction qui perd, ajoute ou déplace un verbe de format décale les
// valeurs : « %d VM » rendu « %s VM » écrit « %!s(int=3) ».
func TestLesTraductionsGardentLeursVerbes(t *testing.T) {
	for fr, en := range anglais {
		a, b := verbeFormat.FindAllString(fr, -1), verbeFormat.FindAllString(en, -1)
		if strings.Join(a, " ") != strings.Join(b, " ") {
			t.Errorf("verbes %v ≠ %v pour %q", a, b, fr)
		}
	}
}

func TestLaLangueSeResoutDansLOrdre(t *testing.T) {
	env := func(v string) func(string) string {
		return func(k string) string {
			if k == "EL_LANG" {
				return v
			}
			return ""
		}
	}
	cas := []struct {
		nom    string
		args   []string
		elLang string
		veut   string
	}{
		{"défaut", nil, "", LangueFr},
		{"EL_LANG anglais", nil, "en", LangueEn},
		{"EL_LANG régional", nil, "en_CA.UTF-8", LangueEn},
		{"langue inconnue", nil, "de", LangueFr},
		{"--lang espacé", []string{"--status", "--lang", "en"}, "", LangueEn},
		{"-lang=", []string{"-lang=en"}, "", LangueEn},
		{"--lang= l'emporte sur EL_LANG", []string{"--lang=fr"}, "en", LangueFr},
		{"--lang sans valeur", []string{"--lang"}, "en", LangueEn},
		{"après --, ce n'est plus une option", []string{"--", "--lang", "en"}, "", LangueFr},
		{"une valeur n'est pas une option", []string{"--age-by", "lang"}, "", LangueFr},
	}
	for _, c := range cas {
		if got := langueDemandee(c.args, env(c.elLang)); got != c.veut {
			t.Errorf("%s : %q, attendu %q", c.nom, got, c.veut)
		}
	}
}

func TestUnMessageSortEnAnglais(t *testing.T) {
	defer definirLangue(LangueFr)
	definirLangue(LangueEn)
	if got := T("écoutes : http %d, tls %d"); got != "listeners: http %d, tls %d" {
		t.Errorf("anglais : %q", got)
	}
	if got := T("texte que le catalogue ignore"); got != "texte que le catalogue ignore" {
		t.Errorf("un texte inconnu doit sortir tel quel, pas %q", got)
	}
	definirLangue(LangueFr)
	if got := T("écoutes : http %d, tls %d"); got != "écoutes : http %d, tls %d" {
		t.Errorf("français : %q", got)
	}
}

// Le Python du menu lit ces libellés de --status et cette phrase du journal
// dans les DEUX langues : une traduction qui s'en écarte le rend aveugle.
func TestLesLibellesLusParLeMenuRestentReconnaissables(t *testing.T) {
	attendus := map[string]string{
		"autorité    : %s\n":                              "authority",
		"empreinte   : %s\n":                              "fingerprint",
		"exceptions  : aucune\n":                          "exceptions",
		"dépôts git  : %d en miroir, %s\n":                "git repos",
		"tunnel opaque retenu pour %s (%d échec(s)) : %v": "opaque tunnel kept for %s (",
	}
	for fr, prefixe := range attendus {
		if !strings.HasPrefix(anglais[fr], prefixe) {
			t.Errorf("%q traduit en %q, qui ne commence plus par %q",
				fr, anglais[fr], prefixe)
		}
	}
}

// L'option doit être DÉCLARÉE : flag.Parse refuse une option inconnue, et
// chaque appel du menu qui la passe échouerait alors avant de rien dire.
// Le binaire est construit et lancé pour de vrai, sur un cache vide.
func TestLeBinaireAccepteLangEtParleAnglais(t *testing.T) {
	if _, err := exec.LookPath("go"); err != nil {
		t.Skip("go absent du PATH")
	}
	dir := t.TempDir()
	bin := filepath.Join(dir, "cache")
	if out, err := exec.Command("go", "build", "-o", bin, ".").CombinedOutput(); err != nil {
		t.Fatalf("construction : %v\n%s", err, out)
	}
	cmd := exec.Command(bin, "--lang", "en", "--status", "--cache-dir", filepath.Join(dir, "vide"),
		"--ca-dir", filepath.Join(dir, "ca"))
	cmd.Env = append(os.Environ(), "EL_LANG=fr")
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("--lang en --status : %v\n%s", err, out)
	}
	if !strings.Contains(string(out), "directory   :") {
		t.Errorf("sortie non anglaise malgré --lang en :\n%s", out)
	}
}
