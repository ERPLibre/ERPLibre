
        function calculerIMCPercentile() {
            var age = parseFloat(document.getElementById('age').value);
            var taille = parseFloat(document.getElementById('taille').value);
            var poids = parseFloat(document.getElementById('poids').value);
            var tailleUnit = document.getElementById('tailleUnit').value;
            var poidsUnit = document.getElementById('poidsUnit').value;
            var gender = document.querySelector('input[name="gender"]:checked').value;
            var ageGroup = document.querySelector('input[name="ageGroup"]:checked').value;
           
             // Vérification des plages d'âge
           
            if (ageGroup === "Bebe" && (age < 0 || age > 24)) {
            alert("L'âge pour les bébés doit être compris entre 0 et 24 mois.");
            return; // Arrête la fonction si l'âge n'est pas valide
        } else if (ageGroup === "Enfant" && (age < 24 || age > 96)) {
            alert("L'âge pour les enfants doit être compris entre 24 et 96 mois.");
            return; // Arrête la fonction si l'âge n'est pas valide
        }
            // Conversion des unités si nécessaire
            if (tailleUnit === "pouces") {
                taille = taille * 2.54; // Conversion pouces en cm
            }
            if (poidsUnit === "livres") {
                poids = poids * 0.453592; // Conversion livres en kg
            }

            // Calcul de la grandeur en mètres
            var grandeur = taille / 100;

            // Calcul de l'IMC
            var IMC = poids / (grandeur * grandeur);

            var percentile;
            var message;

            // Ajustements selon l'âge et le sexe
            if (ageGroup === "Bebe") {
                if (gender === "Garcon") {
                    if (IMC < 14) {
                        percentile = "Sous le 5e percentile";
                        message = `Votre bébé a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est considéré comme insuffisance pondérale. Consultez un pédiatre pour évaluer la santé de votre bébé.`;
                    } else if (IMC >= 14 && IMC < 15.5) {
                        percentile = "5e à 10e percentile";
                        message = `Votre bébé a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est proche de l'insuffisance pondérale. Il est conseillé de surveiller son alimentation.`;
                    } else if (IMC >= 15.5 && IMC < 18) {
                        percentile = "10e à 85e percentile";
                        message = `Votre bébé a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est normal. Assurez-vous qu'il a une alimentation équilibrée.`;
                    } else if (IMC >= 18 && IMC < 20) {
                        percentile = "85e à 95e percentile";
                        message = `Votre bébé a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui peut indiquer un surpoids. Consultez un pédiatre pour évaluer son alimentation.`;
                    } else {
                        percentile = "Au-dessus du 95e percentile";
                        message = `Votre bébé a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est considéré comme obésité. Il est recommandé de consulter un pédiatre.`;
                    }
                } else {
                    if (IMC < 13.5) {
                        percentile = "Sous le 5e percentile";
                        message = `Votre bébé a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est considéré comme insuffisance pondérale. Consultez un pédiatre pour évaluer la santé de votre bébé.`;
                    } else if (IMC >= 13.5 && IMC < 15) {
                        percentile = "5e à 10e percentile";
                        message = `Votre bébé a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est proche de l'insuffisance pondérale. Il est conseillé de surveiller son alimentation.`;
                    } else if (IMC >= 15 && IMC < 17.5) {
                        percentile = "10e à 85e percentile";
                        message = `Votre bébé a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est normal. Assurez-vous qu'il a une alimentation équilibrée.`;
                    } else if (IMC >= 17.5 && IMC < 19.5) {
                        percentile = "85e à 95e percentile";
                        message = `Votre bébé a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui peut indiquer un surpoids. Consultez un pédiatre pour évaluer son alimentation.`;
                    } else {
                        percentile = "Au-dessus du 95e percentile";
                        message = `Votre bébé a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est considéré comme obésité. Il est recommandé de consulter un pédiatre.`;
                    }
                }
            } else {
                // Traitement pour l'âge "Enfant"
                if (gender === "Garcon") {
                    if (IMC < 14) {
                        percentile = "Sous le 5e percentile";
                        message = `Votre enfant a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est considéré comme insuffisance pondérale. Consultez un pédiatre pour évaluer la santé de votre enfant.`;
                    } else if (IMC >= 14 && IMC < 15.5) {
                        percentile = "5e à 10e percentile";
                        message = `Votre enfant a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est proche de l'insuffisance pondérale. Il est conseillé de surveiller son alimentation.`;
                    } else if (IMC >= 15.5 && IMC < 18) {
                        percentile = "10e à 85e percentile";
                        message = `Votre enfant a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est normal. Assurez-vous qu'il a une alimentation équilibrée.`;
                    } else if (IMC >= 18 && IMC < 20) {
                        percentile = "85e à 95e percentile";
                        message = `Votre enfant a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui peut indiquer un surpoids. Consultez un pédiatre pour évaluer son alimentation.`;
                    } else {
                        percentile = "Au-dessus du 95e percentile";
                        message = `Votre enfant a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est considéré comme obésité. Il est recommandé de consulter un pédiatre.`;
                    }
                } else {
                    if (IMC < 13.5) {
                        percentile = "Sous le 5e percentile";
                        message = `Votre enfant a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est considéré comme insuffisance pondérale. Consultez un pédiatre pour évaluer la santé de votre enfant.`;
                    } else if (IMC >= 13.5 && IMC < 15) {
                        percentile = "5e à 10e percentile";
                        message = `Votre enfant a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est proche de l'insuffisance pondérale. Il est conseillé de surveiller son alimentation.`;
                    } else if (IMC >= 15 && IMC < 17.5) {
                        percentile = "10e à 85e percentile";
                        message = `Votre enfant a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est normal. Assurez-vous qu'il a une alimentation équilibrée.`;
                    } else if (IMC >= 17.5 && IMC < 19.5) {
                        percentile = "85e à 95e percentile";
                        message = `Votre enfant a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui peut indiquer un surpoids. Consultez un pédiatre pour évaluer son alimentation.`;
                    } else {
                        percentile = "Au-dessus du 95e percentile";
                        message = `Votre enfant a un IMC de ${IMC.toFixed(2)} à ${age} mois, ce qui est considéré comme obésité. Il est recommandé de consulter un pédiatre.`;
                    }
                }
            }

            var resultatsDiv = document.getElementById('resultats');
            resultatsDiv.innerHTML = `
                
                IMC: ${IMC.toFixed(2)}<br>   
                <p>${message}</p>
            `;

            // Afficher le bouton de recalcul et masquer le formulaire
            document.getElementById('calculatorBox').style.display = 'none';
            document.getElementById('recalculerBtn').style.display = 'block';
            document.getElementById('canvasContainer').style.display = 'block';

            // Choisir l'image du graphique en fonction de l'âge et du sexe
            var imagePath = '';
    if (ageGroup === "Bebe") {
        if(gender === "Garcon"){
            imagePath = 'images/courbe_garcon.png';
        }else{
            imagePath = 'images/courbe_fille.png';
        }
    } else if (ageGroup === "Enfant") {
        if(gender === "Garcon"){
            imagePath = 'images/courbe_garcon.png';
        }else{
            imagePath = 'images/courbe_fille.png';
        }
    }
    
    // Mettre à jour la source de l'image
    var img = new Image();
    img.src = imagePath;

    img.onload = function () {
        // Mettre à jour les dimensions du canvas
        var canvas = document.getElementById('curveCanvas');
        canvas.width = img.width;
        canvas.height = img.height;

        var ctx = canvas.getContext('2d');

        // Effacer le canvas avant de dessiner
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        // Dessiner l'image sur le canvas
        ctx.drawImage(img, 0, 0);

        // Calcul des coordonnées en fonction de l'âge et de l'IMC
        var ageEnAnnee = age / 12; // Convertir l'âge en années si nécessaire
        var ageMin = 0; // L'âge minimum représenté sur le graphique (par exemple, 0 ans)
        var ageMax = 18; // L'âge maximum représenté sur le graphique (par exemple, 20 ans)
        var IMCMin = 11; // L'IMC minimum représenté sur le graphique
        var IMCMax = 34; // L'IMC maximum représenté sur le graphique

        var x = ((ageEnAnnee - ageMin) / (ageMax - ageMin) * canvas.width) + 20;
        var y = (canvas.height - ((IMC - IMCMin) / (IMCMax - IMCMin) * canvas.height))-18;

        console.log(`Age en années: ${ageEnAnnee}`);
        console.log(`IMC: ${IMC}`);
        console.log(`Coordonnée X: ${x}`);
        console.log(`Coordonnée Y: ${y}`);

        // Dessiner le point sur le graphique
        ctx.beginPath();
        ctx.arc(x, y, 5, 0, 2 * Math.PI);
        ctx.fillStyle = 'red';
        ctx.fill();
        ctx.strokeStyle = 'black';
        ctx.stroke();

        // Ajouter un texte pour indiquer la position
        ctx.fillStyle = 'red';
        ctx.fillText("Votre position", x + 10, y); // 'x + 10' décale le texte à droite du point
    };
        }

        function recalculer() {
            document.getElementById('calculatorBox').style.display = 'block';
            document.getElementById('recalculerBtn').style.display = 'none';
            document.getElementById('canvasContainer').style.display = 'none';
            document.getElementById('resultats').innerHTML = '';
             // Vider les champs du formulaire
            document.getElementById('age').value = '';
            document.getElementById('taille').value = '';
            document.getElementById('poids').value = '';
            document.getElementById('tailleUnit').value = 'cm'; // Réinitialiser l'unité par défaut
            document.getElementById('poidsUnit').value = 'kg'; // Réinitialiser l'unité par défaut
        }
